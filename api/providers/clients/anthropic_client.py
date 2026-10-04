"""Anthropic Claude via the official ``anthropic`` SDK (Messages API).

Docs: https://docs.anthropic.com/en/api/messages
Tool use: https://docs.anthropic.com/en/docs/build-with-claude/tool-use
Key check (free): GET /v1/models

Structured output is implemented with a forced ``submit_response`` tool whose input
schema is the requested JSON schema, which works on every current Claude model.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import anthropic

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
from .schema_utils import inline_refs

SUBMIT_TOOL = "submit_response"
DEFAULT_MAX_TOKENS = 8192


class AnthropicClient(ProviderClient):
    info = ProviderInfo(
        name="anthropic",
        label="Anthropic Claude",
        key_url="https://console.anthropic.com/settings/keys",
        docs_url="https://docs.anthropic.com/en/api/overview",
        key_prefix_hint="sk-ant-…",
        test_billing_note=(
            "Testing lists the models available to the key. It does not run a model and is "
            "not billed."
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
        self._client: anthropic.Anthropic | None = None

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(
                api_key=self._api_key, timeout=self.timeout, max_retries=self.max_retries
            )
        return self._client

    def complete(self, request: CompletionRequest) -> CompletionResult:
        system = request.system or ""
        tools: list[dict[str, Any]] = [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.parameters,
            }
            for spec in request.tools
        ]
        kwargs: dict[str, Any] = {}
        if request.response_schema:
            tools.append(
                {
                    "name": SUBMIT_TOOL,
                    "description": "Submit the final answer as structured data.",
                    "input_schema": inline_refs(request.response_schema),
                }
            )
            if request.tools:
                system = (
                    f"{system}\n\nWhen you have everything you need, call `{SUBMIT_TOOL}` "
                    "with your final answer."
                ).strip()
            else:
                kwargs["tool_choice"] = {"type": "tool", "name": SUBMIT_TOOL}
        if tools:
            kwargs["tools"] = tools
        if system:
            kwargs["system"] = system
        if request.temperature is not None:
            kwargs["temperature"] = max(0.0, min(1.0, request.temperature))

        params = {
            "model": request.model,
            "max_tokens": request.max_output_tokens or DEFAULT_MAX_TOKENS,
            "messages": _messages(request.messages),
            **kwargs,
        }
        try:
            response = self._create(params)
        except anthropic.APIError as exc:
            raise self._normalize(exc, request.model) from None

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        submitted: Any = None
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                if block.name == SUBMIT_TOOL:
                    submitted = block.input
                else:
                    tool_calls.append(
                        ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {}))
                    )
        text = "".join(text_parts)
        if submitted is not None:
            text, tool_calls = json.dumps(submitted), []
        elif request.response_schema and not tool_calls:
            text = extract_json_text(text)
        usage = response.usage
        return CompletionResult(
            text=text,
            tool_calls=tool_calls,
            raw_assistant=list(response.content),
            provider=self.name,
            model=response.model or request.model,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            finish_reason=response.stop_reason,
        )

    def _create(self, params: dict[str, Any]) -> Any:
        try:
            return self.client.messages.create(**params)
        except anthropic.BadRequestError as exc:
            # Some Claude models fix sampling parameters; retry once without temperature.
            if "temperature" in params and "temperature" in _error_detail(exc).lower():
                retry = {k: v for k, v in params.items() if k != "temperature"}
                return self.client.messages.create(**retry)
            raise

    def _normalize(self, exc: anthropic.APIError, model: str | None = None) -> LLMError:
        if isinstance(exc, anthropic.APITimeoutError):
            return LLMError(
                friendly_message("timeout", self.label, None),
                kind="timeout",
                provider=self.name,
                retryable=True,
            )
        if isinstance(exc, anthropic.APIConnectionError):
            return LLMError(
                friendly_message("network", self.label, "Check your internet connection."),
                kind="network",
                provider=self.name,
                retryable=True,
            )
        status = getattr(exc, "status_code", None)
        kind, retryable = kind_for_status(status)
        detail = _error_detail(exc)
        if status == 529 or "overloaded" in detail.lower():
            kind, retryable = "provider_error", True
            detail = "Claude is temporarily overloaded. Try again shortly."
        elif status == 404 and model:
            detail = f"“{model}” was not found for this key. Pick another model in Settings."
        elif status == 400 and "credit balance" in detail.lower():
            kind = "quota_exceeded"
        response = getattr(exc, "response", None)
        headers = response.headers if response is not None else {}
        retry_after = headers.get("retry-after") if headers else None
        return LLMError(
            friendly_message(kind, self.label, self.redact(detail)),
            kind=kind,
            provider=self.name,
            status_code=status,
            retryable=retryable,
            retry_after=float(retry_after) if retry_after and retry_after.isdigit() else None,
            request_id=getattr(exc, "request_id", None),
        )

    def list_models(self) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        try:
            for model in self.client.models.list(limit=100):
                capabilities = getattr(model, "capabilities", None)
                structured = getattr(capabilities, "structured_outputs", None)
                models.append(
                    ModelInfo(
                        id=model.id,
                        label=model.display_name or model.id,
                        context_window=getattr(model, "max_input_tokens", None),
                        max_output_tokens=getattr(model, "max_tokens", None),
                        supports_tools=True,
                        supports_structured_output=(
                            bool(getattr(structured, "supported", True)) if structured else True
                        ),
                        supports_temperature=True,
                        temperature_max=1.0,
                    )
                )
        except anthropic.APIError as exc:
            raise self._normalize(exc) from None
        return models

    def test_connection(self) -> ConnectionResult:
        try:
            page = self.client.models.list(limit=5)
            count = len(page.data)
        except anthropic.APIError as exc:
            error = self._normalize(exc)
            return ConnectionResult(False, error.message, error.kind)
        return ConnectionResult(
            True, "Connected to Anthropic. The key is valid.", None, {"models_visible": count}
        )


def _messages(messages: list[Message]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []

    def append(role: str, blocks: list[Any]) -> None:
        if payload and payload[-1]["role"] == role:
            payload[-1]["content"].extend(blocks)
        else:
            payload.append({"role": role, "content": blocks})

    for message in messages:
        if message.role == "tool":
            append(
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id,
                        "content": message.content,
                    }
                ],
            )
        elif message.role == "assistant":
            if isinstance(message.raw, list) and message.raw:
                append("assistant", list(message.raw))
                continue
            blocks: list[Any] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                blocks.append(
                    {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
                )
            if blocks:
                append("assistant", blocks)
        elif message.images:
            user_blocks: list[Any] = []
            if message.content:
                user_blocks.append({"type": "text", "text": message.content})
            for image in message.images:
                if image.text:
                    user_blocks.append({"type": "text", "text": image.text})
                user_blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image.mime_type,
                            "data": base64.b64encode(image.data).decode("ascii"),
                        },
                    }
                )
            append("user", user_blocks)
        elif message.content:
            append("user", [{"type": "text", "text": message.content}])

    if payload and payload[0]["role"] != "user":
        payload.insert(0, {"role": "user", "content": [{"type": "text", "text": "Continue."}]})
    return payload


def _error_detail(exc: anthropic.APIError) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    return str(getattr(exc, "message", "") or "")
