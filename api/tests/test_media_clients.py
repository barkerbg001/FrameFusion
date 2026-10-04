"""ElevenLabs/Pexels clients and engine integration lookups, with HTTP mocked."""

from typing import Any

import httpx
import pytest

from engine import integrations
from engine.services import elevenlabs_client, pexels_client, pexels_footage
from providers import services
from providers.clients.media import ElevenLabsClient, PexelsClient
from providers.models import AppSettings

ELEVEN_KEY = "sk_" + "k" * 40
PEXELS_KEY = "p" * 56


def _transport(handler: Any) -> Any:
    def factory(self: Any) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url, headers=self._headers(), transport=httpx.MockTransport(handler)
        )

    return factory


def test_elevenlabs_test_reports_credits(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/v2/voices":
            return httpx.Response(200, json={"voices": [], "has_more": False})
        return httpx.Response(
            200, json={"tier": "starter", "character_count": 1000, "character_limit": 30000}
        )

    monkeypatch.setattr(ElevenLabsClient, "_http", _transport(handler))
    result = ElevenLabsClient(ELEVEN_KEY).test_connection()
    assert result.ok
    assert "29,000 of 30,000" in result.message
    assert seen[0].headers["xi-api-key"] == ELEVEN_KEY
    assert seen[0].url.params["page_size"] == "1"


def test_elevenlabs_invalid_key_is_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"detail": {"status": "invalid_api_key", "message": f"Bad {ELEVEN_KEY}"}}
        )

    monkeypatch.setattr(ElevenLabsClient, "_http", _transport(handler))
    result = ElevenLabsClient(ELEVEN_KEY).test_connection()
    assert not result.ok
    assert result.kind == "invalid_credentials"
    assert ELEVEN_KEY not in result.message


def test_elevenlabs_voices_and_models(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/voices":
            assert request.url.params["search"] == "calm"
            return httpx.Response(
                200,
                json={
                    "voices": [
                        {
                            "voice_id": "abc",
                            "name": "Calm",
                            "category": "premade",
                            "labels": {"accent": "american", "age": "young"},
                            "preview_url": "https://cdn.example/calm.mp3",
                        }
                    ],
                    "has_more": True,
                    "next_page_token": "tok",
                },
            )
        return httpx.Response(
            200,
            json=[
                {
                    "model_id": "eleven_multilingual_v2",
                    "name": "Multi",
                    "can_do_text_to_speech": True,
                },
                {
                    "model_id": "eleven_english_sts_v2",
                    "name": "STS",
                    "can_do_text_to_speech": False,
                },
            ],
        )

    monkeypatch.setattr(ElevenLabsClient, "_http", _transport(handler))
    client = ElevenLabsClient(ELEVEN_KEY)
    page = client.list_voices(search="calm")
    assert page.voices[0]["preview_url"].endswith("calm.mp3")
    assert page.has_more and page.next_page_token == "tok"
    assert [m["model_id"] for m in client.list_models()] == ["eleven_multilingual_v2"]


def test_elevenlabs_models_fall_back_without_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ElevenLabsClient,
        "_http",
        _transport(lambda request: httpx.Response(403, json={"detail": "missing_permissions"})),
    )
    models = ElevenLabsClient(ELEVEN_KEY).list_models()
    assert models and all(m["source"] == "fallback" for m in models)


def test_pexels_test_reads_quota_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == PEXELS_KEY
        assert request.url.path == "/v1/curated"
        return httpx.Response(
            200,
            json={"photos": []},
            headers={"X-Ratelimit-Limit": "20000", "X-Ratelimit-Remaining": "19990"},
        )

    monkeypatch.setattr(PexelsClient, "_http", _transport(handler))
    result = PexelsClient(PEXELS_KEY).test_connection()
    assert result.ok
    assert result.details == {"limit": 20000, "remaining": 19990}


@pytest.mark.django_db
def test_engine_reads_saved_keys_and_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    assert integrations.is_configured("pexels") is False
    with pytest.raises(integrations.IntegrationNotConfigured, match="Settings"):
        pexels_client.search_pexels_videos("ocean waves")

    services.save_api_key("pexels", PEXELS_KEY)
    app = AppSettings.load()
    app.pexels_orientation = "landscape"
    app.pexels_size = "medium"
    app.save()
    assert integrations.is_configured("pexels") is True

    captured: dict[str, Any] = {}

    def fake_request(base: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        captured.update(base=base, path=path, params=params, key=pexels_client._get_api_key())
        return {
            "videos": [
                {
                    "id": 1,
                    "url": "https://www.pexels.com/video/1/",
                    "user": {"name": "Ana", "url": "https://www.pexels.com/@ana"},
                    "video_files": [{"link": "https://x/1.mp4", "file_type": "video/mp4"}],
                }
            ]
        }

    monkeypatch.setattr(pexels_client, "_request_json", fake_request)
    result = pexels_client.search_pexels_videos("ocean waves")
    assert captured["base"] == "https://api.pexels.com/videos"
    assert captured["params"]["orientation"] == "landscape"
    assert captured["params"]["size"] == "medium"
    assert captured["key"] == PEXELS_KEY
    video = result["videos"][0]
    assert video["attribution"] == "Video by Ana on Pexels"
    assert video["photographer_url"] == "https://www.pexels.com/@ana"

    pexels_client.search_pexels_videos("ocean waves", orientation=None, size=None)
    assert captured["params"]["orientation"] is None


@pytest.mark.django_db
def test_renders_treat_missing_pexels_key_as_a_limitation() -> None:
    with pytest.raises(pexels_footage.PexelsFootageError, match="Settings"):
        pexels_footage.download_pexels_clips("ocean waves", 2)
    with pytest.raises(pexels_footage.PexelsFootageError, match="Settings"):
        pexels_footage.prepare_pexels_background(fallback_query="ocean waves")


@pytest.mark.django_db
def test_speech_uses_saved_voice_model_and_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    services.save_api_key("elevenlabs", ELEVEN_KEY)
    app = AppSettings.load()
    app.elevenlabs_voice_id = "savedVoice"
    app.elevenlabs_model_id = "eleven_flash_v2_5"
    app.elevenlabs_stability = 0.25
    app.save()

    calls: list[dict[str, Any]] = []

    def fake_post(url: str, payload: dict[str, Any], output_path: str, timeout: int) -> None:
        calls.append({"url": url, "payload": payload})
        with open(output_path, "wb") as handle:
            handle.write(b"ID3")

    monkeypatch.setattr(elevenlabs_client, "_post_audio", fake_post)
    elevenlabs_client.generate_speech("Hello", str(tmp_path / "a.mp3"))
    assert "/text-to-speech/savedVoice?" in calls[0]["url"]
    assert calls[0]["payload"]["model_id"] == "eleven_flash_v2_5"
    assert calls[0]["payload"]["voice_settings"] == {"stability": 0.25}

    elevenlabs_client.generate_speech("Hi", str(tmp_path / "b.mp3"), voice_id="other")
    assert "/text-to-speech/other?" in calls[1]["url"]
