import json
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import openai
import pytest
from google.genai import types as genai_types

from engine.llm import CompletionRequest, LLMError, Message, ToolCall, ToolSpec
from providers.clients import redact
from providers.clients.anthropic_client import SUBMIT_TOOL, AnthropicClient
from providers.clients.base import extract_json_text
from providers.clients.gemini import GeminiClient, _contents
from providers.clients.openrouter import OpenRouterClient
from providers.clients.schema_utils import inline_refs

OR_KEY = "sk-or-v1-feedfacefeedfacefeedface"
ANT_KEY = "sk-ant-api03-feedfacefeedfacefeedface"


def _tool() -> ToolSpec:
    return ToolSpec(
        name="search",
        description="Search the web.",
        parameters={"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
        function=lambda q: q,
    )


class _Recorder:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_openrouter_builds_openai_payload_and_parses_tool_calls() -> None:
    client = OpenRouterClient(OR_KEY)
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_1",
                            function=SimpleNamespace(name="search", arguments='{"q": "tides"}'),
                        )
                    ],
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=3),
        model="openai/gpt-4o-mini",
    )
    recorder = _Recorder(completion)
    client._client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=SimpleNamespace(create=recorder))
    )
    result = client.complete(
        CompletionRequest(
            model="openai/gpt-4o-mini",
            system="You plan videos.",
            messages=[
                Message(role="user", content="Hi"),
                Message(
                    role="assistant",
                    tool_calls=[ToolCall(id="call_0", name="search", arguments={"q": "x"})],
                ),
                Message(
                    role="tool", content='{"ok": true}', tool_call_id="call_0", tool_name="search"
                ),
            ],
            tools=[_tool()],
            response_schema={"type": "object", "properties": {"a": {"type": "string"}}},
            temperature=0.5,
            max_output_tokens=300,
        )
    )
    sent = recorder.calls[0]
    assert sent["messages"][0] == {"role": "system", "content": "You plan videos."}
    assert sent["messages"][2]["tool_calls"][0]["function"]["arguments"] == '{"q": "x"}'
    assert sent["messages"][3] == {
        "role": "tool",
        "tool_call_id": "call_0",
        "content": '{"ok": true}',
    }
    assert sent["tools"][0]["function"]["name"] == "search"
    assert sent["response_format"]["json_schema"]["strict"] is False
    assert sent["temperature"] == 0.5 and sent["max_tokens"] == 300
    assert result.tool_calls == [ToolCall(id="call_1", name="search", arguments={"q": "tides"})]
    assert (result.input_tokens, result.output_tokens) == (10, 3)


def _status_error(cls: type, status: int, message: str) -> Exception:
    request = httpx.Request("POST", "https://example.test")
    response = httpx.Response(status, request=request, headers={"retry-after": "7"})
    return cls(message, response=response, body={"error": {"message": message}})


def test_openrouter_normalizes_errors_without_leaking_keys() -> None:
    client = OpenRouterClient(OR_KEY)
    client._client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=_Recorder(
                    _status_error(openai.AuthenticationError, 401, f"Invalid key {OR_KEY}")
                )
            )
        )
    )
    with pytest.raises(LLMError) as raised:
        client.complete(CompletionRequest(model="m", messages=[Message(role="user", content="x")]))
    error = raised.value
    assert error.kind == "invalid_credentials"
    assert error.provider == "openrouter"
    assert OR_KEY not in error.message
    assert "rejected" in error.message

    client._client.chat.completions.create = _Recorder(  # type: ignore[union-attr,method-assign]
        _status_error(openai.RateLimitError, 429, "Slow down")
    )
    with pytest.raises(LLMError) as limited:
        client.complete(CompletionRequest(model="m", messages=[Message(role="user", content="x")]))
    assert limited.value.kind == "rate_limited"
    assert limited.value.retryable is True
    assert limited.value.retry_after == 7.0


def test_anthropic_structured_output_uses_forced_tool() -> None:
    client = AnthropicClient(ANT_KEY)
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="tool_use", id="tu_1", name=SUBMIT_TOOL, input={"title": "Tides"})
        ],
        usage=SimpleNamespace(input_tokens=20, output_tokens=8),
        model="claude-haiku-4-5",
        stop_reason="tool_use",
    )
    recorder = _Recorder(response)
    client._client = SimpleNamespace(messages=SimpleNamespace(create=recorder))  # type: ignore[assignment]
    schema = {
        "type": "object",
        "properties": {"title": {"$ref": "#/$defs/Title"}},
        "$defs": {"Title": {"type": "string"}},
    }
    result = client.complete(
        CompletionRequest(
            model="claude-haiku-4-5",
            system="Return JSON.",
            messages=[Message(role="user", content="Name it")],
            response_schema=schema,
            temperature=1.7,
        )
    )
    sent = recorder.calls[0]
    assert sent["tool_choice"] == {"type": "tool", "name": SUBMIT_TOOL}
    assert sent["tools"][0]["input_schema"]["properties"]["title"] == {"type": "string"}
    assert sent["temperature"] == 1.0
    assert sent["max_tokens"] == 8192
    assert json.loads(result.text) == {"title": "Tides"}
    assert result.tool_calls == []


def test_anthropic_groups_tool_results_into_user_turn() -> None:
    client = AnthropicClient(ANT_KEY)
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="All done")],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        model="claude-haiku-4-5",
        stop_reason="end_turn",
    )
    recorder = _Recorder(response)
    client._client = SimpleNamespace(messages=SimpleNamespace(create=recorder))  # type: ignore[assignment]
    client.complete(
        CompletionRequest(
            model="claude-haiku-4-5",
            messages=[
                Message(role="user", content="Go"),
                Message(
                    role="assistant",
                    tool_calls=[
                        ToolCall(id="a", name="search", arguments={"q": "1"}),
                        ToolCall(id="b", name="search", arguments={"q": "2"}),
                    ],
                ),
                Message(role="tool", content="r1", tool_call_id="a"),
                Message(role="tool", content="r2", tool_call_id="b"),
            ],
            tools=[_tool()],
        )
    )
    messages = recorder.calls[0]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert [b["tool_use_id"] for b in messages[2]["content"]] == ["a", "b"]


def test_anthropic_overloaded_is_retryable_provider_error() -> None:
    client = AnthropicClient(ANT_KEY)
    error = _status_error(anthropic.InternalServerError, 529, "Overloaded")
    client._client = SimpleNamespace(messages=SimpleNamespace(create=_Recorder(error)))  # type: ignore[assignment]
    with pytest.raises(LLMError) as raised:
        client.complete(
            CompletionRequest(
                model="claude-haiku-4-5", messages=[Message(role="user", content="x")]
            )
        )
    assert raised.value.kind == "provider_error"
    assert raised.value.retryable is True


def test_gemini_contents_group_function_responses_and_keep_raw_turns() -> None:
    raw = genai_types.Content(
        role="model",
        parts=[genai_types.Part(function_call=genai_types.FunctionCall(name="search", args={}))],
    )
    contents = _contents(
        [
            Message(role="user", content="Hi"),
            Message(role="assistant", raw=raw, tool_calls=[ToolCall("1", "search", {})]),
            Message(role="tool", content='{"hits": 2}', tool_call_id="1", tool_name="search"),
            Message(role="tool", content="plain text", tool_call_id="2", tool_name="search"),
        ]
    )
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert contents[1] is raw
    responses = [p.function_response for p in contents[2].parts or [] if p.function_response]
    assert responses[0].response == {"hits": 2}
    assert responses[1].response == {"result": "plain text"}


def test_gemini_complete_parses_function_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GeminiClient("AIza" + "x" * 35)
    candidate = SimpleNamespace(
        content=genai_types.Content(
            role="model",
            parts=[
                genai_types.Part(text="thinking", thought=True),
                genai_types.Part(
                    function_call=genai_types.FunctionCall(name="search", args={"q": "tide"})
                ),
            ],
        ),
        finish_reason="STOP",
    )
    response = SimpleNamespace(
        candidates=[candidate],
        usage_metadata=SimpleNamespace(prompt_token_count=5, candidates_token_count=2),
        model_version="gemini-flash-latest",
    )
    recorder = _Recorder(response)
    client._client = SimpleNamespace(models=SimpleNamespace(generate_content=recorder))  # type: ignore[assignment]
    result = client.complete(
        CompletionRequest(
            model="gemini-flash-latest",
            messages=[Message(role="user", content="Find tides")],
            tools=[_tool()],
            response_schema={"type": "object", "title": "Report", "properties": {}},
        )
    )
    config = recorder.calls[0]["config"]
    assert config.automatic_function_calling.disable is True
    assert config.response_mime_type is None
    assert "JSON schema" in config.system_instruction
    assert result.text == ""
    assert result.tool_calls[0].name == "search"
    assert result.tool_calls[0].arguments == {"q": "tide"}
    assert result.raw_assistant is candidate.content


def test_redact_and_json_extraction() -> None:
    text = f"bad key {OR_KEY} and {ANT_KEY} and AIza{'Q' * 30}"
    cleaned = redact(text)
    assert OR_KEY not in cleaned and ANT_KEY not in cleaned and "AIza" not in cleaned
    eleven, pexels = "sk_" + "a1" * 12, "Ab3" * 18 + "xy"
    media_cleaned = redact(f"xi-api-key {eleven} Authorization {pexels}")
    assert eleven not in media_cleaned and pexels not in media_cleaned
    assert extract_json_text('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json_text('Sure! {"a": 1} hope that helps') == '{"a": 1}'


def test_inline_refs_resolves_nested_definitions() -> None:
    schema = {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"$ref": "#/$defs/Item"}}},
        "$defs": {"Item": {"type": "object", "properties": {"n": {"type": "integer"}}}},
    }
    resolved = inline_refs(schema)
    assert "$defs" not in resolved
    assert resolved["properties"]["items"]["items"]["properties"]["n"] == {"type": "integer"}
