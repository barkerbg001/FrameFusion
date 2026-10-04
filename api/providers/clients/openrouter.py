"""OpenRouter via its OpenAI-compatible Chat Completions API.

Docs: https://openrouter.ai/docs/api-reference/overview
Key check (free): GET https://openrouter.ai/api/v1/key
Models: GET https://openrouter.ai/api/v1/models?supported_parameters=tools
"""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any

import httpx
import openai

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

BASE_URL = "https://openrouter.ai/api/v1"
APP_HEADERS = {
    "HTTP-Referer": "https://github.com/framefusion",
    "X-OpenRouter-Title": "FrameFusion",
    "X-Title": "FrameFusion",
}


class OpenRouterClient(ProviderClient):
    info = ProviderInfo(
        name="openrouter",
        label="OpenRouter",
        key_url="https://openrouter.ai/settings/keys",
        docs_url="https://openrouter.ai/docs/api-reference/overview",
        key_prefix_hint="sk-or-v1-…",
        test_billing_note=(
            "Testing calls OpenRouter's key-info endpoint. It does not run a model and "
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
        self._client: openai.OpenAI | None = None

    @property
    def client(self) -> openai.OpenAI:
        if self._client is None:
            self._client = openai.OpenAI(
                api_key=self._api_key,
                base_url=BASE_URL,
                timeout=self.timeout,
                max_retries=self.max_retries,
                default_headers=APP_HEADERS,
            )
        return self._client

    # --- chat ---------------------------------------------------------------------------

    def _messages(self, request: CompletionRequest, system: str | None) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        if system:
            payload.append({"role": "system", "content": system})
        for message in request.messages:
            payload.append(_message_payload(message))
        return payload

    def complete(self, request: CompletionRequest) -> CompletionResult:
        system = request.system
        kwargs: dict[str, Any] = {}
        if request.tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": spec.parameters,
                    },
                }
                for spec in request.tools
            ]
        if request.response_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": False,
                    "schema": inline_refs(request.response_schema),
                },
            }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_output_tokens:
            kwargs["max_tokens"] = request.max_output_tokens

        messages: Any = self._messages(request, system)
        try:
            response = self.client.chat.completions.create(
                model=request.model, messages=messages, **kwargs
            )
        except openai.APIError as exc:
            raise self._normalize(exc, request.model) from None

        error = getattr(response, "error", None)
        if not response.choices:
            detail = error.get("message") if isinstance(error, dict) else None
            raise LLMError(
                friendly_message("provider_error", self.label, self.redact(detail or "")),
                kind="provider_error",
                provider=self.name,
            )

        choice = response.choices[0]
        message = choice.message
        tool_calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            function = getattr(call, "function", None)
            if function is None:
                continue
            tool_calls.append(
                ToolCall(
                    id=call.id or f"call_{uuid.uuid4().hex[:12]}",
                    name=function.name,
                    arguments=_parse_arguments(function.arguments),
                )
            )
        text = message.content or ""
        if request.response_schema and not tool_calls:
            text = extract_json_text(text)
        usage = response.usage
        return CompletionResult(
            text=text,
            tool_calls=tool_calls,
            provider=self.name,
            model=response.model or request.model,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            finish_reason=choice.finish_reason,
        )

    def _normalize(self, exc: openai.APIError, model: str | None = None) -> LLMError:
        if isinstance(exc, openai.APITimeoutError):
            return LLMError(
                friendly_message("timeout", self.label, None),
                kind="timeout",
                provider=self.name,
                retryable=True,
            )
        if isinstance(exc, openai.APIConnectionError):
            return LLMError(
                friendly_message("network", self.label, "Check your internet connection."),
                kind="network",
                provider=self.name,
                retryable=True,
            )
        status = getattr(exc, "status_code", None)
        kind, retryable = kind_for_status(status)
        detail = _error_detail(exc)
        lowered = detail.lower()
        if status in (400, 404) and "image input" in lowered:
            kind = "unsupported"
            detail = f"“{model}” does not accept image input."
        elif status in (400, 404) and ("no endpoints" in lowered or "not a valid model" in lowered):
            kind = "model_unavailable"
            detail = (
                f"“{model}” is unavailable or does not support the features this agent needs "
                "(tool calling / structured output). Pick another model in Settings."
            )
        response = getattr(exc, "response", None)
        headers = response.headers if response is not None else {}
        return LLMError(
            friendly_message(kind, self.label, self.redact(detail)),
            kind=kind,
            provider=self.name,
            status_code=status,
            retryable=retryable,
            retry_after=_float(headers.get("retry-after")),
            request_id=headers.get("x-request-id") or headers.get("x-generation-id"),
        )

    # --- discovery ----------------------------------------------------------------------

    def _http(self) -> httpx.Client:
        return httpx.Client(
            base_url=BASE_URL,
            timeout=self.timeout,
            headers={"Authorization": f"Bearer {self._api_key}", **APP_HEADERS},
        )

    def list_models(self) -> list[ModelInfo]:
        try:
            with self._http() as http:
                response = http.get("/models", params={"supported_parameters": "tools"})
        except httpx.TimeoutException:
            raise LLMError(
                friendly_message("timeout", self.label, None), kind="timeout", provider=self.name
            ) from None
        except httpx.HTTPError:
            raise LLMError(
                friendly_message("network", self.label, None), kind="network", provider=self.name
            ) from None
        if response.status_code != 200:
            raise self._http_error(response)
        models: list[ModelInfo] = []
        for item in response.json().get("data", []):
            params = set(item.get("supported_parameters") or [])
            top = item.get("top_provider") or {}
            models.append(
                ModelInfo(
                    id=item["id"],
                    label=item.get("name") or item["id"],
                    context_window=item.get("context_length"),
                    max_output_tokens=top.get("max_completion_tokens"),
                    supports_tools="tools" in params,
                    supports_structured_output=bool(
                        params & {"structured_outputs", "response_format"}
                    ),
                    supports_temperature="temperature" in params,
                    temperature_max=2.0 if "temperature" in params else None,
                )
            )
        models.sort(key=lambda m: m.label.lower())
        return models

    def test_connection(self) -> ConnectionResult:
        try:
            with self._http() as http:
                response = http.get("/key")
        except httpx.TimeoutException:
            return ConnectionResult(False, friendly_message("timeout", self.label, None), "timeout")
        except httpx.HTTPError:
            return ConnectionResult(
                False,
                friendly_message("network", self.label, "Check your internet connection."),
                "network",
            )
        if response.status_code != 200:
            error = self._http_error(response)
            return ConnectionResult(False, error.message, error.kind)
        data = response.json().get("data", {}) or {}
        details = {
            "label": data.get("label"),
            "is_free_tier": data.get("is_free_tier"),
            "limit_remaining": data.get("limit_remaining"),
        }
        remaining = data.get("limit_remaining")
        if isinstance(remaining, int | float) and remaining <= 0:
            return ConnectionResult(
                False,
                friendly_message("quota_exceeded", self.label, "The key has no credit remaining."),
                "quota_exceeded",
                details,
            )
        return ConnectionResult(True, "Connected to OpenRouter. The key is valid.", None, details)

    def _http_error(self, response: httpx.Response) -> LLMError:
        kind, retryable = kind_for_status(response.status_code)
        detail = ""
        try:
            body = response.json()
            detail = (body.get("error") or {}).get("message", "") if isinstance(body, dict) else ""
        except ValueError:
            pass
        return LLMError(
            friendly_message(kind, self.label, self.redact(detail)),
            kind=kind,
            provider=self.name,
            status_code=response.status_code,
            retryable=retryable,
            retry_after=_float(response.headers.get("retry-after")),
        )


def _message_payload(message: Message) -> dict[str, Any]:
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in message.tool_calls
            ],
        }
    if message.role == "user" and message.images:
        parts: list[dict[str, Any]] = []
        if message.content:
            parts.append({"type": "text", "text": message.content})
        for image in message.images:
            if image.text:
                parts.append({"type": "text", "text": image.text})
            encoded = base64.b64encode(image.data).decode("ascii")
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image.mime_type};base64,{encoded}"},
                }
            )
        return {"role": "user", "content": parts}
    return {"role": message.role, "content": message.content}


def _parse_arguments(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _error_detail(exc: openai.APIError) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if body.get("message"):
            return str(body["message"])
    return str(getattr(exc, "message", "") or "")


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None
