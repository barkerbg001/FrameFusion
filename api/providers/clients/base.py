"""Shared pieces for provider clients."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from engine.llm import CompletionRequest, CompletionResult, ErrorKind, LLMError


@dataclass
class ModelInfo:
    id: str
    label: str
    context_window: int | None = None
    max_output_tokens: int | None = None
    supports_tools: bool | None = None
    supports_structured_output: bool | None = None
    supports_temperature: bool = True
    temperature_max: float | None = None
    source: str = "discovered"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConnectionResult:
    ok: bool
    message: str
    kind: ErrorKind | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "message": self.message, "kind": self.kind, "details": self.details}


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    label: str
    key_url: str
    docs_url: str
    key_prefix_hint: str
    test_billing_note: str
    capabilities: dict[str, bool]


class ProviderClient:
    """Base class: one instance per (saved key, request/job)."""

    info: ProviderInfo

    def __init__(self, api_key: str, *, timeout: float = 120, max_retries: int = 2) -> None:
        if not api_key:
            raise LLMError("No API key provided.", kind="not_configured", provider=self.name)
        self._api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries

    @property
    def name(self) -> str:
        return self.info.name

    @property
    def label(self) -> str:
        return self.info.label

    def complete(self, request: CompletionRequest) -> CompletionResult:
        raise NotImplementedError

    def list_models(self) -> list[ModelInfo]:
        raise NotImplementedError

    def test_connection(self) -> ConnectionResult:
        raise NotImplementedError

    def redact(self, text: str) -> str:
        return redact(text, self._api_key)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} provider={self.name}>"


_KEY_PATTERNS = [
    re.compile(r"sk-or-v1-[A-Za-z0-9]{8,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"sk_[A-Za-z0-9]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{56}(?![A-Za-z0-9])"),
]


def redact(text: str, secret: str | None = None) -> str:
    if not text:
        return text
    if secret:
        text = text.replace(secret, "[redacted]")
    for pattern in _KEY_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text[:600]


def kind_for_status(status: int | None) -> tuple[ErrorKind, bool]:
    if status == 401:
        return "invalid_credentials", False
    if status == 402:
        return "quota_exceeded", False
    if status == 403:
        return "permission_denied", False
    if status == 404:
        return "model_unavailable", False
    if status == 408:
        return "timeout", True
    if status == 429:
        return "rate_limited", True
    if status is not None and status >= 500:
        return "provider_error", True
    if status is not None and status >= 400:
        return "bad_request", False
    return "provider_error", False


FRIENDLY_PREFIX: dict[ErrorKind, str] = {
    "invalid_credentials": "The API key was rejected",
    "permission_denied": "The API key does not have access to this resource",
    "rate_limited": "Rate limit reached",
    "quota_exceeded": "The account has run out of credits or quota",
    "model_unavailable": "The selected model is not available",
    "bad_request": "The provider rejected the request",
    "timeout": "The provider took too long to respond",
    "network": "Could not reach the provider",
    "provider_error": "The provider returned an error",
    "unsupported": "This feature is not supported",
    "not_configured": "Not configured",
    "encryption_unavailable": "Encryption is not configured",
}


def friendly_message(kind: ErrorKind, label: str, detail: str | None) -> str:
    base = f"{label}: {FRIENDLY_PREFIX.get(kind, 'Request failed')}"
    if kind == "rate_limited":
        base += ". Wait a moment and try again"
    return f"{base}. {detail}" if detail else f"{base}."


def extract_json_text(text: str) -> str:
    """Return the JSON object in a model reply, tolerating code fences or preamble."""
    stripped = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1).strip()
    try:
        json.loads(stripped)
        return stripped
    except ValueError:
        pass
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        candidate = stripped[start : end + 1]
        try:
            json.loads(candidate)
            return candidate
        except ValueError:
            pass
    return stripped
