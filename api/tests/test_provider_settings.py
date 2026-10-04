import json
from typing import Any

import pytest
from rest_framework.test import APIClient

from providers.clients import ConnectionResult
from providers.clients.media import ElevenLabsClient, PexelsClient, VoicePage
from providers.clients.openrouter import OpenRouterClient
from providers.crypto import decrypt_secret
from providers.models import AppSettings, ProviderCredential

pytestmark = pytest.mark.django_db

KEY = "sk-or-v1-abcdef0123456789abcdef0123456789"  # gitleaks:allow (dummy)
ELEVEN_KEY = "sk_" + "e" * 44 + "ELVN"
PEXELS_KEY = "P" * 52 + "PXLS"


def test_saved_key_is_encrypted_and_masked(client: APIClient) -> None:
    response = client.put("/api/settings/providers/openrouter/key", {"api_key": KEY}, format="json")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["masked_key"] == "••••6789"
    assert body["status"] == "configured"
    assert KEY not in json.dumps(body)

    credential = ProviderCredential.objects.get(provider="openrouter")
    assert KEY not in credential.encrypted_key
    assert decrypt_secret(credential.encrypted_key) == KEY

    listing = client.get("/api/settings/providers").json()
    assert listing["encryption_configured"] is True
    assert KEY not in json.dumps(listing)
    by_name = {p["provider"]: p for p in listing["providers"]}
    assert set(by_name) == {
        "openrouter",
        "gemini",
        "anthropic",
        "elevenlabs",
        "pexels",
        "pixabay",
        "brave",
    }
    assert by_name["openrouter"]["configured"] is True
    assert by_name["openrouter"]["kind"] == "ai"
    assert by_name["gemini"]["status"] == "unconfigured"
    assert by_name["anthropic"]["configured"] is False
    assert by_name["elevenlabs"]["kind"] == "media"
    assert by_name["pexels"]["key_url"].startswith("https://www.pexels.com/")


@pytest.mark.parametrize(
    ("service", "key", "hint"), [("elevenlabs", ELEVEN_KEY, "ELVN"), ("pexels", PEXELS_KEY, "PXLS")]
)
def test_media_keys_are_encrypted_masked_and_removable(
    client: APIClient, service: str, key: str, hint: str
) -> None:
    saved = client.put(f"/api/settings/providers/{service}/key", {"api_key": key}, format="json")
    assert saved.status_code == 200
    assert saved.json()["masked_key"] == f"••••{hint}"
    assert key not in json.dumps(saved.json())
    credential = ProviderCredential.objects.get(provider=service)
    assert key not in credential.encrypted_key
    assert decrypt_secret(credential.encrypted_key) == key

    app = client.get("/api/app").json()
    assert app["integrations"][service]["configured"] is True
    assert key not in json.dumps(app)

    removed = client.delete(f"/api/settings/providers/{service}/key").json()
    assert removed["configured"] is False
    assert not ProviderCredential.objects.filter(provider=service).exists()


def test_replace_and_remove_key(client: APIClient) -> None:
    client.put(
        "/api/settings/providers/anthropic/key", {"api_key": "sk-ant-" + "a" * 30}, format="json"
    )
    replaced = client.put(
        "/api/settings/providers/anthropic/key",
        {"api_key": "sk-ant-" + "b" * 26 + "WXYZ"},
        format="json",
    ).json()
    assert replaced["masked_key"] == "••••WXYZ"
    assert ProviderCredential.objects.count() == 1

    removed = client.delete("/api/settings/providers/anthropic/key").json()
    assert removed["configured"] is False
    assert not ProviderCredential.objects.exists()


def test_key_validation(client: APIClient) -> None:
    assert (
        client.put(
            "/api/settings/providers/gemini/key", {"api_key": "short"}, format="json"
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/api/settings/providers/gemini/key", {"api_key": "AIza abc defghijk"}, format="json"
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/api/settings/providers/unknown/key", {"api_key": KEY}, format="json"
        ).status_code
        == 404
    )


def test_saving_fails_clearly_without_encryption_key(client: APIClient, settings: Any) -> None:
    settings.FRAMEFUSION_ENCRYPTION_KEYS = []
    response = client.put("/api/settings/providers/openrouter/key", {"api_key": KEY}, format="json")
    assert response.status_code == 503
    assert response.json()["code"] == "encryption_unavailable"
    assert "FRAMEFUSION_ENCRYPTION_KEY" in response.json()["detail"]
    assert client.get("/api/settings/providers").json()["encryption_configured"] is False


def test_connection_test_records_status(client: APIClient, monkeypatch: pytest.MonkeyPatch) -> None:
    client.put("/api/settings/providers/openrouter/key", {"api_key": KEY}, format="json")
    seen: list[str] = []

    def fake_test(self: OpenRouterClient) -> ConnectionResult:
        seen.append(self._api_key)
        return ConnectionResult(
            False, "OpenRouter: The API key was rejected.", "invalid_credentials"
        )

    monkeypatch.setattr(OpenRouterClient, "test_connection", fake_test)
    response = client.post("/api/settings/providers/openrouter/test", {}, format="json").json()
    assert seen == [KEY]
    assert response["result"]["ok"] is False
    assert response["result"]["kind"] == "invalid_credentials"
    assert response["provider"]["status"] == "failed"
    assert KEY not in json.dumps(response)

    monkeypatch.setattr(
        OpenRouterClient, "test_connection", lambda self: ConnectionResult(True, "Connected.")
    )
    ok = client.post("/api/settings/providers/openrouter/test", {}, format="json").json()
    assert ok["provider"]["status"] == "valid"


def test_media_connection_tests_use_saved_key(
    client: APIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.put("/api/settings/providers/pexels/key", {"api_key": PEXELS_KEY}, format="json")
    seen: list[str] = []

    def fake_test(self: PexelsClient) -> ConnectionResult:
        seen.append(self._api_key)
        return ConnectionResult(True, "Connected to Pexels.", None, {"remaining": 10})

    monkeypatch.setattr(PexelsClient, "test_connection", fake_test)
    body = client.post("/api/settings/providers/pexels/test", {}, format="json").json()
    assert seen == [PEXELS_KEY]
    assert body["provider"]["status"] == "valid"
    assert PEXELS_KEY not in json.dumps(body)


def test_unsaved_key_can_be_tested_without_saving(
    client: APIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        OpenRouterClient, "test_connection", lambda self: ConnectionResult(True, "Connected.")
    )
    response = client.post(
        "/api/settings/providers/openrouter/test", {"api_key": KEY}, format="json"
    ).json()
    assert response["tested"] == "unsaved_key"
    assert response["result"]["ok"] is True
    assert not ProviderCredential.objects.exists()
    nothing = client.post("/api/settings/providers/gemini/test", {}, format="json")
    assert nothing.status_code == 400


def test_models_fall_back_without_key(client: APIClient) -> None:
    body = client.get("/api/settings/providers/anthropic/models").json()
    assert body["source"] == "fallback"
    assert [m["id"] for m in body["models"]] == ["claude-sonnet-4-5", "claude-haiku-4-5"]
    assert body["error"]
    assert client.get("/api/settings/providers/pexels/models").status_code == 404


def test_ai_settings_persist_and_report_readiness(client: APIClient) -> None:
    initial = client.get("/api/settings/ai").json()
    assert initial["readiness"]["planner"]["ready"] is False
    assert "default AI provider" in initial["readiness"]["planner"]["problem"]

    client.put("/api/settings/providers/openrouter/key", {"api_key": KEY}, format="json")
    saved = client.put(
        "/api/settings/ai",
        {
            "default_provider": "openrouter",
            "default_model": "openai/gpt-4o-mini",
            "temperature": 0.4,
            "max_output_tokens": 2048,
            "overrides": {"production": {"provider": "anthropic", "model": "claude-haiku-4-5"}},
        },
        format="json",
    ).json()
    assert saved["default_model"] == "openai/gpt-4o-mini"
    assert saved["temperature"] == 0.4
    assert saved["overrides"]["production"] == {
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
    }
    assert saved["readiness"]["planner"]["ready"] is True
    production = saved["readiness"]["production"]
    assert production["ready"] is False
    assert "Anthropic Claude" in production["problem"]

    again = client.get("/api/settings/ai").json()
    assert again["overrides"]["production"]["model"] == "claude-haiku-4-5"

    cleared = client.put(
        "/api/settings/ai",
        {
            "default_provider": "openrouter",
            "default_model": "openai/gpt-4o-mini",
            "overrides": {"production": None},
        },
        format="json",
    ).json()
    assert cleared["overrides"]["production"] is None
    assert cleared["readiness"]["production"]["ready"] is True


def test_ai_settings_validation(client: APIClient) -> None:
    missing_model = client.put(
        "/api/settings/ai", {"default_provider": "gemini", "default_model": ""}, format="json"
    )
    assert missing_model.status_code == 400
    hot = client.put(
        "/api/settings/ai",
        {"default_provider": "gemini", "default_model": "gemini-flash-latest", "temperature": 3},
        format="json",
    )
    assert hot.status_code == 400


def test_media_settings_persist(client: APIClient) -> None:
    initial = client.get("/api/settings/media").json()
    assert initial["elevenlabs"]["model_id"] == "eleven_multilingual_v2"
    assert initial["pexels"]["orientation"] == "portrait"
    assert initial["integrations"]["elevenlabs"]["configured"] is False

    saved = client.put(
        "/api/settings/media",
        {
            "elevenlabs": {
                "voice_id": "abcDEF123",
                "voice_name": "Narrator",
                "model_id": "eleven_flash_v2_5",
                "music_model": "music_v1",
                "voice_settings": {"stability": 0.4, "speed": 1.1, "use_speaker_boost": False},
            },
            "pexels": {"media_type": "photo", "orientation": "landscape", "size": "medium"},
        },
        format="json",
    ).json()
    assert saved["elevenlabs"]["voice_id"] == "abcDEF123"
    assert saved["elevenlabs"]["voice_settings"]["stability"] == 0.4
    assert saved["elevenlabs"]["voice_settings"]["similarity_boost"] is None
    assert saved["pexels"] == {"media_type": "photo", "orientation": "landscape", "size": "medium"}
    app = AppSettings.load()
    assert app.elevenlabs_speed == 1.1
    assert app.elevenlabs_speaker_boost is False

    bad = client.put(
        "/api/settings/media",
        {"elevenlabs": {"voice_id": "../etc", "model_id": "x"}},
        format="json",
    )
    assert bad.status_code == 400
    slow = client.put(
        "/api/settings/media",
        {"elevenlabs": {"model_id": "x", "voice_settings": {"speed": 3}}},
        format="json",
    )
    assert slow.status_code == 400


def test_voice_listing_requires_key_and_never_returns_it(
    client: APIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = client.get("/api/settings/media/elevenlabs/voices")
    assert missing.status_code == 409
    assert "ElevenLabs" in missing.json()["detail"]

    client.put("/api/settings/providers/elevenlabs/key", {"api_key": ELEVEN_KEY}, format="json")
    seen: list[dict[str, Any]] = []

    def fake_voices(self: ElevenLabsClient, **kwargs: Any) -> VoicePage:
        seen.append({"key": self._api_key, **kwargs})
        return VoicePage(
            voices=[
                {
                    "voice_id": "v1",
                    "name": "Ava",
                    "category": "premade",
                    "description": "",
                    "labels": {"accent": "british"},
                    "preview_url": "https://example.com/ava.mp3",
                }
            ],
            has_more=False,
            next_page_token=None,
        )

    monkeypatch.setattr(ElevenLabsClient, "list_voices", fake_voices)
    body = client.get("/api/settings/media/elevenlabs/voices?search=ava").json()
    assert body["voices"][0]["name"] == "Ava"
    assert seen[0]["key"] == ELEVEN_KEY
    assert seen[0]["search"] == "ava"
    assert ELEVEN_KEY not in json.dumps(body)


def test_narration_defaults_to_free_edge_and_persists(client: APIClient) -> None:
    body = client.get("/api/settings/narration").json()
    assert body["provider"] == "edge"
    assert body["readiness"]["ready"] is True
    assert body["readiness"]["requires_key"] is False
    edge = next(p for p in body["providers"] if p["id"] == "edge")
    assert edge["online"] is True
    assert "Microsoft" in edge["disclosure"]
    assert "offline" not in json.dumps(body).lower()

    saved = client.put(
        "/api/settings/narration",
        {
            "provider": "edge",
            "edge": {
                "voice": "en-GB-SoniaNeural",
                "voice_label": "Sonia · English (UK)",
                "rate": 15,
                "pitch": -5,
                "volume": 10,
            },
        },
        format="json",
    )
    assert saved.status_code == 200
    app = AppSettings.objects.get()
    assert (app.edge_voice, app.edge_rate, app.edge_pitch, app.edge_volume) == (
        "en-GB-SoniaNeural",
        15,
        -5,
        10,
    )
    assert client.get("/api/settings/narration").json()["edge"]["voice"] == "en-GB-SoniaNeural"
    assert client.get("/api/app").json()["narration"]["voice"] == "en-GB-SoniaNeural"

    bad = client.put(
        "/api/settings/narration",
        {"provider": "edge", "edge": {"voice": "en-US-Bad;rm", "rate": 500}},
        format="json",
    )
    assert bad.status_code == 400


def test_choosing_elevenlabs_without_a_key_is_reported_not_hidden(client: APIClient) -> None:
    body = client.put("/api/settings/narration", {"provider": "elevenlabs"}, format="json").json()
    assert body["provider"] == "elevenlabs"
    assert body["readiness"]["ready"] is False
    assert "ElevenLabs API key" in body["readiness"]["problem"]

    preview = client.post("/api/narration/preview", {"text": "Hello"}, format="json")
    assert preview.status_code == 409
    assert preview.json()["code"] == "not_configured"

    client.put("/api/settings/providers/elevenlabs/key", {"api_key": ELEVEN_KEY}, format="json")
    body = client.get("/api/settings/narration").json()
    assert body["readiness"]["ready"] is True
    assert ELEVEN_KEY not in json.dumps(body)
