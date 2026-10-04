"""Google Gemini via the official ``google-genai`` SDK.

Docs: https://ai.google.dev/gemini-api/docs
Function calling: https://ai.google.dev/gemini-api/docs/function-calling
Structured output: https://ai.google.dev/gemini-api/docs/structured-output
Key check (free): models.list
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from engine.llm import CompletionRequest, CompletionResult, LLMError, Message, ToolCall

from .base import (
    ConnectionResult,
    ModelInfo,
    ProviderClient,
    ProviderInfo,
    extract_json_text,
    friendly_message,
    kind_for_status,
)
from .schema_utils import inline_refs, strip_keys

_UNSUPPORTED_SCHEMA_KEYS = {"title", "additionalProperties", "$schema"}


class GeminiClient(ProviderClient):
    info = ProviderInfo(
        name="gemini",
        label="Google Gemini",
        key_url="https://aistudio.google.com/app/apikey",
        docs_url="https://ai.google.dev/gemini-api/docs",
        key_prefix_hint="AIza…",
        test_billing_note=(
            "Testing lists the models available to the key. It does not generate content and "
            "is not billed."
        ),
        capabilities={
            "tools": True,
            "structured_output": True,
            "temperature": True,
            "max_output_tokens": True,
            "model_discovery": True,
        },
    )

    def __init__(self, api_key: str, *, timeout: float = 120, max_retries: int = 2) -> None:
        super().__init__(api_key, timeout=timeout, max_retries=max_retries)
        self._client: genai.Client | None = None

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(
                    timeout=int(self.timeout * 1000),
                    retry_options=types.HttpRetryOptions(attempts=self.max_retries + 1),
                ),
            )
        return self._client

    def complete(self, request: CompletionRequest) -> CompletionResult:
        system = request.system or ""
        config: dict[str, Any] = {
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        }
        if request.tools:
            config["tools"] = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=spec.name,
                            description=spec.description,
                            parameters_json_schema=strip_keys(
                                spec.parameters, {"additionalProperties"}
                            ),
                        )
                        for spec in request.tools
                    ]
                )
            ]
        if request.response_schema:
            schema = strip_keys(inline_refs(request.response_schema), _UNSUPPORTED_SCHEMA_KEYS)
            if request.tools:
                # Older Gemini models reject JSON mode combined with function calling.
                system = (
                    f"{system}\n\nWhen you give your final answer, reply with only a JSON "
                    f"object matching this JSON schema:\n{json.dumps(schema)}"
                ).strip()
            else:
                config["response_mime_type"] = "application/json"
                config["response_json_schema"] = schema
        if system:
            config["system_instruction"] = system
        if request.temperature is not None:
            config["temperature"] = request.temperature
        if request.max_output_tokens:
            config["max_output_tokens"] = request.max_output_tokens

        contents: Any = _contents(request.messages)
        try:
            response = self.client.models.generate_content(
                model=request.model,
                contents=contents,
                config=types.GenerateContentConfig(**config),
            )
        except genai_errors.APIError as exc:
            raise self._normalize(exc, request.model) from None
        except httpx.TimeoutException:
            raise LLMError(
                friendly_message("timeout", self.label, None),
                kind="timeout",
                provider=self.name,
                retryable=True,
            ) from None
        except httpx.HTTPError:
            raise LLMError(
                friendly_message("network", self.label, "Check your internet connection."),
                kind="network",
                provider=self.name,
                retryable=True,
            ) from None

        if not response.candidates:
            feedback = getattr(response, "prompt_feedback", None)
            reason = getattr(feedback, "block_reason", None)
            raise LLMError(
                friendly_message(
                    "bad_request",
                    self.label,
                    f"The prompt was blocked ({reason})." if reason else "No response returned.",
                ),
                kind="bad_request",
                provider=self.name,
            )

        candidate = response.candidates[0]
        content = candidate.content
        parts = list(content.parts or []) if content else []
        text = "".join(part.text for part in parts if part.text and not part.thought)
        tool_calls = [
            ToolCall(
                id=part.function_call.id or f"call_{uuid.uuid4().hex[:12]}",
                name=part.function_call.name or "",
                arguments=dict(part.function_call.args or {}),
            )
            for part in parts
            if part.function_call is not None
        ]
        if request.response_schema and not tool_calls:
            text = extract_json_text(text)
        usage = response.usage_metadata
        finish = getattr(candidate, "finish_reason", None)
        return CompletionResult(
            text=text,
            tool_calls=tool_calls,
            raw_assistant=content,
            provider=self.name,
            model=getattr(response, "model_version", None) or request.model,
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
            finish_reason=str(finish) if finish is not None else None,
        )

    def _normalize(self, exc: genai_errors.APIError, model: str | None = None) -> LLMError:
        code = getattr(exc, "code", None)
        status = str(getattr(exc, "status", "") or "")
        detail = str(getattr(exc, "message", "") or "")
        kind, retryable = kind_for_status(code)
        if "API_KEY_INVALID" in detail or "API key not valid" in detail:
            kind, retryable = "invalid_credentials", False
        elif status == "RESOURCE_EXHAUSTED" or code == 429:
            kind, retryable = "rate_limited", True
            if "quota" in detail.lower():
                detail = "Quota exceeded for this key. Check your Google AI Studio plan."
        elif code == 404 and model:
            detail = f"“{model}” was not found for this key. Pick another model in Settings."
        return LLMError(
            friendly_message(kind, self.label, self.redact(detail)),
            kind=kind,
            provider=self.name,
            status_code=code,
            retryable=retryable,
        )

    def list_models(self) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        try:
            for model in self.client.models.list(config={"page_size": 100}):
                actions = model.supported_actions or []
                if "generateContent" not in actions:
                    continue
                model_id = (model.name or "").removeprefix("models/")
                lowered = model_id.lower()
                if any(word in lowered for word in ("embedding", "imagen", "aqa", "tts", "image")):
                    continue
                models.append(
                    ModelInfo(
                        id=model_id,
                        label=model.display_name or model_id,
                        context_window=model.input_token_limit,
                        max_output_tokens=model.output_token_limit,
                        supports_tools=None,
                        supports_structured_output=None,
                        supports_temperature=True,
                        temperature_max=model.max_temperature,
                    )
                )
        except genai_errors.APIError as exc:
            raise self._normalize(exc) from None
        except httpx.TimeoutException:
            raise LLMError(
                friendly_message("timeout", self.label, None), kind="timeout", provider=self.name
            ) from None
        except httpx.HTTPError:
            raise LLMError(
                friendly_message("network", self.label, None), kind="network", provider=self.name
            ) from None
        models.sort(key=lambda m: m.label.lower())
        return models

    def test_connection(self) -> ConnectionResult:
        try:
            pager = self.client.models.list(config={"page_size": 5})
            count = len(list(pager.page))
        except genai_errors.APIError as exc:
            error = self._normalize(exc)
            return ConnectionResult(False, error.message, error.kind)
        except httpx.TimeoutException:
            return ConnectionResult(False, friendly_message("timeout", self.label, None), "timeout")
        except httpx.HTTPError:
            return ConnectionResult(
                False,
                friendly_message("network", self.label, "Check your internet connection."),
                "network",
            )
        return ConnectionResult(
            True, "Connected to Google Gemini. The key is valid.", None, {"models_visible": count}
        )


def _contents(messages: list[Message]) -> list[types.Content]:
    contents: list[types.Content] = []
    pending_responses: list[types.Part] = []

    def flush() -> None:
        if pending_responses:
            contents.append(types.Content(role="user", parts=list(pending_responses)))
            pending_responses.clear()

    for message in messages:
        if message.role == "tool":
            pending_responses.append(
                types.Part.from_function_response(
                    name=message.tool_name or "tool", response=_tool_response(message.content)
                )
            )
            continue
        flush()
        if message.role == "assistant":
            if isinstance(message.raw, types.Content):
                # Keeps thought signatures that Gemini 3 requires on follow-up turns.
                contents.append(message.raw)
                continue
            parts = [types.Part.from_text(text=message.content)] if message.content else []
            for call in message.tool_calls:
                parts.append(
                    types.Part(
                        function_call=types.FunctionCall(
                            id=call.id, name=call.name, args=call.arguments
                        )
                    )
                )
            contents.append(types.Content(role="model", parts=parts or [types.Part(text="")]))
        else:
            user_parts = [types.Part.from_text(text=message.content)] if message.content else []
            for image in message.images:
                if image.text:
                    user_parts.append(types.Part.from_text(text=image.text))
                user_parts.append(types.Part.from_bytes(data=image.data, mime_type=image.mime_type))
            contents.append(
                types.Content(role="user", parts=user_parts or [types.Part.from_text(text="")])
            )
    flush()
    return contents


def _tool_response(content: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except ValueError:
        return {"result": content}
    return value if isinstance(value, dict) else {"result": value}
