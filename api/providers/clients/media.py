"""ElevenLabs and Pexels clients used by Settings (key test, voice and model discovery,
voice preview). Rendering code in ``engine/services`` makes the production calls.

ElevenLabs docs: https://elevenlabs.io/docs/api-reference/introduction
  Key check (no credits): GET /v2/voices?page_size=1, GET /v1/user/subscription
  Voices: GET /v2/voices   Models: GET /v1/models   Speech (uses credits): POST /v1/text-to-speech
Pexels docs: https://www.pexels.com/api/documentation/
  Key check: GET /v1/curated?per_page=1 (counts against the 200/hour, 20,000/month quota)
Pixabay docs: https://pixabay.com/api/docs/
  Key check: GET /api/?key=…&q=mountain (100 requests per minute; the key is a query parameter
  by design, so URLs are never logged or echoed)
Brave Search docs: https://api-dashboard.search.brave.com/app/documentation/image-search
  Key check: GET /res/v1/images/search?q=lighthouse&count=1 (billed as one request)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from engine.llm import LLMError

from .base import ConnectionResult, ProviderInfo, friendly_message, kind_for_status, redact

ELEVENLABS_URL = "https://api.elevenlabs.io"
PEXELS_URL = "https://api.pexels.com"
PIXABAY_URL = "https://pixabay.com"
BRAVE_URL = "https://api.search.brave.com"

PREVIEW_MAX_CHARS = 300

# Used when the key lacks the models_read permission.
FALLBACK_TTS_MODELS = [
    {"model_id": "eleven_multilingual_v2", "name": "Eleven Multilingual v2", "description": ""},
    {"model_id": "eleven_flash_v2_5", "name": "Eleven Flash v2.5", "description": ""},
    {"model_id": "eleven_turbo_v2_5", "name": "Eleven Turbo v2.5", "description": ""},
    {"model_id": "eleven_v3", "name": "Eleven v3", "description": ""},
]
MUSIC_MODELS = [
    {"model_id": "music_v1", "name": "Eleven Music v1"},
    {"model_id": "music_v2", "name": "Eleven Music v2"},
]


@dataclass
class VoicePage:
    voices: list[dict[str, Any]]
    has_more: bool
    next_page_token: str | None


class MediaServiceClient:
    info: ProviderInfo
    base_url: str

    def __init__(self, api_key: str, *, timeout: float = 30) -> None:
        if not api_key:
            raise LLMError("No API key provided.", kind="not_configured", provider=self.info.name)
        self._api_key = api_key
        self.timeout = timeout

    @property
    def label(self) -> str:
        return self.info.label

    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _http(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, headers=self._headers(), timeout=self.timeout)

    def _error_detail(self, response: httpx.Response) -> str:
        return ""

    def _error(self, response: httpx.Response) -> LLMError:
        kind, retryable = kind_for_status(response.status_code)
        if kind == "model_unavailable":
            kind = "bad_request"
        detail = redact(self._error_detail(response), self._api_key)
        return LLMError(
            friendly_message(kind, self.label, detail),
            kind=kind,
            provider=self.info.name,
            status_code=response.status_code,
            retryable=retryable,
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            with self._http() as http:
                response = http.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise LLMError(
                friendly_message("timeout", self.label, None),
                kind="timeout",
                provider=self.info.name,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(
                friendly_message("network", self.label, "Check your internet connection."),
                kind="network",
                provider=self.info.name,
                retryable=True,
            ) from exc
        if response.status_code >= 400:
            raise self._error(response)
        return response

    def test_connection(self) -> ConnectionResult:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"


class ElevenLabsClient(MediaServiceClient):
    info = ProviderInfo(
        name="elevenlabs",
        label="ElevenLabs",
        key_url="https://elevenlabs.io/app/settings/api-keys",
        docs_url="https://elevenlabs.io/docs/api-reference/introduction",
        key_prefix_hint="sk_…",
        test_billing_note=(
            "Testing lists your voices and reads your subscription. It does not generate audio "
            "and uses no credits."
        ),
        capabilities={"voices": True, "speech": True, "music": True},
    )
    base_url = ELEVENLABS_URL

    def _headers(self) -> dict[str, str]:
        return {"xi-api-key": self._api_key, "Accept": "application/json"}

    def _error_detail(self, response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return ""
        detail = body.get("detail") if isinstance(body, dict) else None
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("status") or "")
        if isinstance(detail, str):
            return detail
        return ""

    def test_connection(self) -> ConnectionResult:
        try:
            self._request("GET", "/v2/voices", params={"page_size": 1})
        except LLMError as exc:
            return ConnectionResult(False, exc.message, exc.kind)
        details: dict[str, Any] = {}
        message = "Connected to ElevenLabs. The key is valid."
        try:
            sub = self._request("GET", "/v1/user/subscription").json()
        except LLMError:
            # Restricted keys may lack user_read; the voice list already proved the key.
            sub = None
        if isinstance(sub, dict):
            used, limit = sub.get("character_count"), sub.get("character_limit")
            details = {"tier": sub.get("tier"), "character_count": used, "character_limit": limit}
            if isinstance(used, int) and isinstance(limit, int) and limit > 0:
                message += f" {max(limit - used, 0):,} of {limit:,} credits left this period."
                if used >= limit:
                    return ConnectionResult(
                        False,
                        friendly_message("quota_exceeded", self.label, "No credits left."),
                        "quota_exceeded",
                        details,
                    )
        return ConnectionResult(True, message, None, details)

    def list_voices(
        self, *, search: str = "", page_size: int = 100, next_page_token: str | None = None
    ) -> VoicePage:
        params: dict[str, Any] = {"page_size": max(1, min(page_size, 100))}
        if search:
            params["search"] = search[:100]
        if next_page_token:
            params["next_page_token"] = next_page_token
        data = self._request("GET", "/v2/voices", params=params).json()
        voices = []
        for voice in data.get("voices") or []:
            labels = voice.get("labels") or {}
            voices.append(
                {
                    "voice_id": voice.get("voice_id", ""),
                    "name": voice.get("name") or "Untitled voice",
                    "category": voice.get("category") or "",
                    "description": (voice.get("description") or "")[:300],
                    "labels": {k: str(v) for k, v in labels.items() if isinstance(v, str | int)},
                    "preview_url": voice.get("preview_url") or "",
                }
            )
        return VoicePage(
            voices=voices,
            has_more=bool(data.get("has_more")),
            next_page_token=data.get("next_page_token") or None,
        )

    def list_models(self) -> list[dict[str, Any]]:
        try:
            data = self._request("GET", "/v1/models").json()
        except LLMError as exc:
            if exc.kind in {"permission_denied", "bad_request"}:
                return [dict(m, source="fallback") for m in FALLBACK_TTS_MODELS]
            raise
        models = []
        for model in data if isinstance(data, list) else []:
            if not model.get("can_do_text_to_speech"):
                continue
            models.append(
                {
                    "model_id": model.get("model_id", ""),
                    "name": model.get("name") or model.get("model_id", ""),
                    "description": (model.get("description") or "")[:240],
                    "source": "discovered",
                }
            )
        return models or [dict(m, source="fallback") for m in FALLBACK_TTS_MODELS]

    def preview_speech(
        self,
        *,
        text: str,
        voice_id: str,
        model_id: str,
        voice_settings: dict[str, Any] | None = None,
    ) -> bytes:
        body: dict[str, Any] = {"text": text[:PREVIEW_MAX_CHARS], "model_id": model_id}
        if voice_settings:
            body["voice_settings"] = voice_settings
        response = self._request(
            "POST",
            f"/v1/text-to-speech/{voice_id}",
            params={"output_format": "mp3_44100_128"},
            json=body,
            headers={"Accept": "audio/mpeg"},
        )
        return response.content


class PexelsClient(MediaServiceClient):
    info = ProviderInfo(
        name="pexels",
        label="Pexels",
        key_url="https://www.pexels.com/api/",
        docs_url="https://www.pexels.com/api/documentation/",
        key_prefix_hint="56 characters",
        test_billing_note=(
            "Pexels is free. Testing makes one request, which counts toward the 200 requests "
            "per hour and 20,000 per month allowance."
        ),
        capabilities={"photos": True, "videos": True},
    )
    base_url = PEXELS_URL

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self._api_key, "Accept": "application/json"}

    def _error_detail(self, response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return ""
        if isinstance(body, dict):
            return str(body.get("error") or body.get("code") or "")
        return ""

    def test_connection(self) -> ConnectionResult:
        try:
            response = self._request("GET", "/v1/curated", params={"per_page": 1})
        except LLMError as exc:
            return ConnectionResult(False, exc.message, exc.kind)
        details: dict[str, Any] = {}
        message = "Connected to Pexels. The key is valid."
        limit = response.headers.get("X-Ratelimit-Limit")
        remaining = response.headers.get("X-Ratelimit-Remaining")
        if limit and remaining and limit.isdigit() and remaining.isdigit():
            details = {"limit": int(limit), "remaining": int(remaining)}
            message += f" {int(remaining):,} of {int(limit):,} requests left this month."
        return ConnectionResult(True, message, None, details)


class PixabayClient(MediaServiceClient):
    info = ProviderInfo(
        name="pixabay",
        label="Pixabay",
        key_url="https://pixabay.com/api/docs/",
        docs_url="https://pixabay.com/api/docs/",
        key_prefix_hint="digits-hex, e.g. 1234567-abc…",
        test_billing_note=(
            "Pixabay is free. Testing makes one search, which counts toward the limit of "
            "100 requests per minute. Results are cached for 24 hours as Pixabay requires."
        ),
        capabilities={"photos": True, "illustrations": True},
    )
    base_url = PIXABAY_URL

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    def _error(self, response: httpx.Response) -> LLMError:
        # Pixabay answers a bad key with 400 and a plain-text message.
        if response.status_code in (400, 401, 403) and "key" in response.text.lower():
            return LLMError(
                friendly_message("invalid_credentials", self.label, "The API key was rejected."),
                kind="invalid_credentials",
                provider=self.info.name,
                status_code=response.status_code,
            )
        return super()._error(response)

    def test_connection(self) -> ConnectionResult:
        try:
            response = self._request(
                "GET", "/api/", params={"key": self._api_key, "q": "mountain", "per_page": 3}
            )
        except LLMError as exc:
            return ConnectionResult(False, exc.message, exc.kind)
        message = "Connected to Pixabay. The key is valid."
        remaining = response.headers.get("X-RateLimit-Remaining")
        details: dict[str, Any] = {}
        if remaining and remaining.isdigit():
            details = {"remaining": int(remaining)}
            message += f" {int(remaining)} requests left this minute."
        return ConnectionResult(True, message, None, details)


class BraveSearchClient(MediaServiceClient):
    info = ProviderInfo(
        name="brave",
        label="Brave Search",
        key_url="https://api-dashboard.search.brave.com/app/keys",
        docs_url="https://api-dashboard.search.brave.com/app/documentation/image-search",
        key_prefix_hint="BSA…",
        test_billing_note=(
            "Brave Search is a paid API (with a monthly free credit). Testing makes one image "
            "search, which is billed as one request. Image search results are for discovery "
            "only: their reuse rights are unknown and you review them before use."
        ),
        capabilities={"image_search": True},
    )
    base_url = BRAVE_URL

    def _headers(self) -> dict[str, str]:
        return {"X-Subscription-Token": self._api_key, "Accept": "application/json"}

    def test_connection(self) -> ConnectionResult:
        try:
            self._request("GET", "/res/v1/images/search", params={"q": "lighthouse", "count": 1})
        except LLMError as exc:
            return ConnectionResult(False, exc.message, exc.kind)
        return ConnectionResult(True, "Connected to Brave Search. The key is valid.", None, {})


MEDIA_CLIENTS: dict[str, type[MediaServiceClient]] = {
    "elevenlabs": ElevenLabsClient,
    "pexels": PexelsClient,
    "pixabay": PixabayClient,
    "brave": BraveSearchClient,
}
