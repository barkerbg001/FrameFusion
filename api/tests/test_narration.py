"""Narration: the Edge TTS adapter, provider routing, retries and the narration jobs.

edge-tts is replaced by ``FakeCommunicate``; nothing here reaches the network.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from edge_tts import exceptions as edge_exc
from rest_framework.test import APIClient

from engine.runtime import RunCancelled, run_context
from engine.services import edge_tts_client, narration
from engine.services.text_video_creator import timed_screen_durations
from providers import services
from providers.models import AppSettings
from studio.jobs import error_payload
from studio.models import GenerationJob, MediaAsset, Project

pytestmark = pytest.mark.django_db

ELEVEN_KEY = "sk_" + "e" * 44 + "ELVN"


class FakeCommunicate:
    plans: list[Any] = []
    calls: list[dict[str, Any]] = []

    def __init__(self, text: str, voice: str, **kwargs: Any) -> None:
        FakeCommunicate.calls.append({"text": text, "voice": voice, **kwargs})
        self.plan = FakeCommunicate.plans.pop(0) if FakeCommunicate.plans else "ok"

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        if isinstance(self.plan, BaseException):
            yield {"type": "audio", "data": b"partial"}
            raise self.plan
        yield {"type": "WordBoundary", "offset": 0, "duration": 4_000_000, "text": "Hello"}
        yield {"type": "audio", "data": b"ID3-fake-audio"}
        yield {"type": "WordBoundary", "offset": 5_000_000, "duration": 4_000_000, "text": "world"}


@pytest.fixture
def fake_edge(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[FakeCommunicate]]:
    FakeCommunicate.plans = []
    FakeCommunicate.calls = []
    monkeypatch.setattr("edge_tts.Communicate", FakeCommunicate)
    monkeypatch.setattr(edge_tts_client.time, "sleep", lambda _s: None)
    monkeypatch.setattr(narration, "audio_duration", lambda _p: 1.25)
    monkeypatch.setattr(narration, "normalize_loudness", lambda _p: True)
    yield FakeCommunicate


@pytest.fixture
def no_paid_speech(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(**_kwargs: Any) -> None:
        raise AssertionError("ElevenLabs must never be called as a fallback")

    monkeypatch.setattr("engine.services.elevenlabs_client.generate_speech", forbidden)


# --- Edge TTS adapter ---------------------------------------------------------------------


def test_edge_applies_voice_and_controls_and_keeps_real_word_timings(
    fake_edge: type[FakeCommunicate], tmp_path: Path
) -> None:
    path = tmp_path / "speech.mp3"
    speech = edge_tts_client.synthesize(
        "Hello world", path, voice="en-GB-SoniaNeural", rate=20, pitch=-10, volume=5
    )
    call = fake_edge.calls[0]
    assert call["voice"] == "en-GB-SoniaNeural"
    assert (call["rate"], call["pitch"], call["volume"]) == ("+20%", "-10Hz", "+5%")
    assert call["boundary"] == "WordBoundary"
    assert speech.words == [(0.0, 0.4, "Hello"), (0.5, 0.9, "world")]
    assert path.read_bytes() == b"ID3-fake-audio"


def test_edge_controls_are_clamped() -> None:
    assert edge_tts_client.prosody(500, -500, 99) == {
        "rate": "+100%",
        "pitch": "-50Hz",
        "volume": "+50%",
    }


def test_edge_retries_network_errors_then_succeeds(
    fake_edge: type[FakeCommunicate], tmp_path: Path
) -> None:
    fake_edge.plans = [aiohttp.ClientConnectionError("down"), "ok"]
    speech = edge_tts_client.synthesize("Hello world", tmp_path / "a.mp3")
    assert len(fake_edge.calls) == 2
    assert speech.path.read_bytes() == b"ID3-fake-audio"


def test_edge_gives_up_after_bounded_retries_and_removes_partial_audio(
    fake_edge: type[FakeCommunicate], tmp_path: Path
) -> None:
    fake_edge.plans = [TimeoutError("slow")] * 5
    path = tmp_path / "a.mp3"
    with pytest.raises(edge_tts_client.EdgeTTSError) as caught:
        edge_tts_client.synthesize("Hello world", path)
    assert len(fake_edge.calls) == edge_tts_client.MAX_ATTEMPTS
    assert caught.value.retryable is True
    assert "internet" in str(caught.value)
    assert not path.exists()


def test_edge_reports_a_voice_that_returns_no_audio(
    fake_edge: type[FakeCommunicate], tmp_path: Path
) -> None:
    fake_edge.plans = [edge_exc.NoAudioReceived("none"), edge_exc.NoAudioReceived("none")]
    with pytest.raises(edge_tts_client.EdgeTTSError, match="voice may be unavailable"):
        edge_tts_client.synthesize("Hello", tmp_path / "a.mp3", voice="en-US-GoneNeural")
    assert len(fake_edge.calls) == 2


def test_edge_rejects_a_voice_missing_from_the_cached_list(
    fake_edge: type[FakeCommunicate], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        edge_tts_client, "_voice_cache", (time.monotonic(), [{"id": "en-US-AvaNeural"}])
    )
    with pytest.raises(edge_tts_client.EdgeTTSError, match="no longer offered"):
        edge_tts_client.synthesize("Hello", tmp_path / "a.mp3", voice="en-US-GoneNeural")
    with pytest.raises(edge_tts_client.EdgeTTSError, match="not a valid"):
        edge_tts_client.synthesize("Hello", tmp_path / "a.mp3", voice="../../etc")
    assert fake_edge.calls == []


def test_edge_cancellation_stops_and_cleans_up(
    fake_edge: type[FakeCommunicate], tmp_path: Path
) -> None:
    checks = {"count": 0}

    def cancel_on_second_check() -> None:
        checks["count"] += 1
        if checks["count"] >= 2:
            raise RunCancelled()

    path = tmp_path / "a.mp3"
    with run_context(None, cancel_on_second_check), pytest.raises(RunCancelled):
        edge_tts_client.synthesize("Hello world", path)
    assert len(fake_edge.calls) == 1
    assert not path.exists()


def test_edge_cancel_check_runs_outside_the_event_loop(
    fake_edge: type[FakeCommunicate], tmp_path: Path
) -> None:
    calls = {"count": 0}

    def database_like_check() -> None:
        # Mirrors Django's SynchronousOnlyOperation guard for ORM calls.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            calls["count"] += 1
            return
        raise AssertionError("cancel check ran inside the event loop")

    with run_context(None, database_like_check):
        edge_tts_client.synthesize("Hello world", tmp_path / "a.mp3")
    assert calls["count"] >= 2


def test_voice_list_is_mapped_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    fetches: list[int] = []

    async def fake_list_voices() -> list[dict[str, Any]]:
        fetches.append(1)
        return [
            {
                "ShortName": "fr-FR-DeniseNeural",
                "FriendlyName": "Microsoft Denise Online (Natural) - French (France)",
                "Locale": "fr-FR",
                "Gender": "Female",
                "Status": "GA",
                "VoiceTag": {"VoicePersonalities": ["Warm"], "ContentCategories": ["News"]},
            }
        ]

    monkeypatch.setattr("edge_tts.list_voices", fake_list_voices)
    first = edge_tts_client.list_voices()
    second = edge_tts_client.list_voices()
    assert first == second
    assert len(fetches) == 1
    assert first[0] == {
        "id": "fr-FR-DeniseNeural",
        "name": "Denise",
        "locale": "fr-FR",
        "locale_name": "French (France)",
        "gender": "Female",
        "status": "GA",
        "personalities": ["Warm"],
        "categories": ["News"],
    }


def test_voice_list_network_failure_is_a_clear_error(
    client: APIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def offline() -> list[dict[str, Any]]:
        raise aiohttp.ClientConnectionError("no route")

    monkeypatch.setattr("edge_tts.list_voices", offline)
    response = client.get("/api/settings/narration/edge/voices")
    assert response.status_code == 502
    assert response.json()["code"] == "voices_unavailable"
    assert "internet" in response.json()["detail"]


# --- Provider routing ---------------------------------------------------------------------


def test_default_narration_uses_edge_without_any_key(
    fake_edge: type[FakeCommunicate], tmp_path: Path, no_paid_speech: None
) -> None:
    app = AppSettings.load()
    app.edge_voice = "en-AU-NatashaNeural"
    app.edge_rate = 10
    app.save()
    result = narration.synthesize("Hello world", tmp_path / "n.wav")
    assert result.provider == "edge"
    assert result.path.suffix == ".mp3"
    assert result.duration_seconds == 1.25
    assert result.normalized is True
    assert fake_edge.calls[0]["voice"] == "en-AU-NatashaNeural"
    assert fake_edge.calls[0]["rate"] == "+10%"


def test_free_failure_never_falls_back_to_elevenlabs(
    fake_edge: type[FakeCommunicate], tmp_path: Path, no_paid_speech: None
) -> None:
    services.save_api_key("elevenlabs", ELEVEN_KEY)
    fake_edge.plans = [ConnectionError("offline")] * 5
    with pytest.raises(narration.NarrationError) as caught:
        narration.synthesize("Hello world", tmp_path / "n.mp3")
    assert caught.value.provider == "edge"
    assert not (tmp_path / "n.mp3").exists()


def test_elevenlabs_is_used_only_when_selected(
    fake_edge: type[FakeCommunicate], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_speech(**kwargs: Any) -> None:
        calls.append(kwargs)
        Path(kwargs["output_path"]).write_bytes(b"ID3-eleven")

    monkeypatch.setattr("engine.services.elevenlabs_client.generate_speech", fake_speech)
    services.save_api_key("elevenlabs", ELEVEN_KEY)
    app = AppSettings.load()
    app.narration_provider = "elevenlabs"
    app.elevenlabs_voice_id = "voice42"
    app.save()

    result = narration.synthesize("Hello world", tmp_path / "n.mp3")
    assert result.provider == "elevenlabs"
    assert calls[0]["voice_id"] == "voice42"
    assert fake_edge.calls == []


def test_elevenlabs_without_a_key_fails_clearly_and_does_not_use_edge(
    fake_edge: type[FakeCommunicate], tmp_path: Path
) -> None:
    app = AppSettings.load()
    app.narration_provider = "elevenlabs"
    app.save()
    with pytest.raises(narration.NarrationError, match="no ElevenLabs API key"):
        narration.synthesize("Hello world", tmp_path / "n.mp3")
    assert fake_edge.calls == []


def test_project_override_beats_the_default() -> None:
    assert narration.current_config().provider == "edge"
    with narration.project_override("elevenlabs", "voice7", "Rachel"):
        config = narration.current_config()
    assert (config.provider, config.voice, config.voice_label, config.source) == (
        "elevenlabs",
        "voice7",
        "Rachel",
        "project",
    )
    assert narration.current_config().source == "default"


# --- Captions -----------------------------------------------------------------------------


def test_captions_follow_word_timings() -> None:
    screens = ["one two", "three four five", "six"]
    words = [
        (0.0, 0.3, "one"),
        (0.4, 0.7, "two"),
        (1.0, 1.3, "three"),
        (1.4, 1.7, "four"),
        (1.8, 2.1, "five"),
        (3.0, 3.4, "six"),
    ]
    durations = timed_screen_durations(screens, words, 4.0)
    assert durations == pytest.approx([1.0, 2.0, 1.0])


def test_captions_fall_back_to_proportional_when_timings_do_not_match() -> None:
    durations = timed_screen_durations(["one two", "three four"], [(0.0, 0.2, "x")], 4.0)
    assert durations == pytest.approx([2.0, 2.0])
    assert timed_screen_durations(["a b"], [], 3.0) == pytest.approx([3.0])


# --- Failure, retry and preview jobs ------------------------------------------------------


def test_narration_failure_keeps_a_private_render_spec(
    fake_edge: type[FakeCommunicate], no_paid_speech: None
) -> None:
    from engine.services.video_producer import produce_sound_short

    fake_edge.plans = [ConnectionError("offline")] * 5
    with pytest.raises(narration.NarrationStageError) as caught:
        produce_sound_short("A calm morning", "#101010", "#FFFFFF", 72, "calm.mp4")
    try:
        raise RuntimeError("Production pipeline failed") from caught.value
    except RuntimeError as wrapped:
        payload = error_payload(wrapped)
    assert payload["kind"] == "narration_failed"
    assert payload["provider"] == "edge"
    assert "Settings → Narration" in payload["message"]
    assert payload["render_spec"]["text"] == "A calm morning"


def _failed_narration_job(project: Project) -> GenerationJob:
    return GenerationJob.objects.create(
        project=project,
        kind=GenerationJob.Kind.PRODUCTION,
        agent="director",
        status=GenerationJob.Status.FAILED,
        input={"task": "x"},
        error={
            "kind": "narration_failed",
            "message": "Edge TTS (free) narration failed.",
            "provider": "edge",
            "retryable": True,
            "render_spec": {
                "text": "A calm morning",
                "background_color": "#101010",
                "text_color": "#FFFFFF",
                "font_size": 72,
                "output_name": "calm.mp4",
                "pexels_background": None,
            },
        },
    )


def test_retry_narration_reuses_the_script_and_renders_a_video(
    client: APIClient, monkeypatch: pytest.MonkeyPatch, output_dir: Path, no_paid_speech: None
) -> None:
    project = Project.objects.create(title="Calm")
    failed = _failed_narration_job(project)
    detail = client.get(f"/api/jobs/{failed.pk}").json()
    assert "render_spec" not in detail["error"]
    assert detail["error"]["can_retry_narration"] is True

    seen: list[Any] = []

    def fake_render(spec: dict[str, Any], config: narration.NarrationConfig) -> dict[str, Any]:
        seen.append((spec, config))
        (output_dir / "abcdef0123_calm.mp4").write_bytes(b"\x00" * 64)
        return {"output_path": str(output_dir / "abcdef0123_calm.mp4")}

    monkeypatch.setattr("engine.services.video_producer.produce_sound_short_from_spec", fake_render)
    response = client.post(f"/api/jobs/{failed.pk}/retry-narration", {}, format="json")
    assert response.status_code == 202
    job = response.json()
    assert job["kind"] == "narration"
    assert job["status"] == "succeeded", job["error"]
    spec, config = seen[0]
    assert spec["text"] == "A calm morning"
    assert config.provider == "edge"
    assert MediaAsset.objects.filter(project=project, kind="video").count() == 1
    assert project.messages.filter(content__contains="Edge TTS").exists()


def test_retry_narration_with_an_explicit_provider_choice(
    client: APIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = Project.objects.create(title="Calm")
    failed = _failed_narration_job(project)
    blocked = client.post(
        f"/api/jobs/{failed.pk}/retry-narration", {"provider": "elevenlabs"}, format="json"
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "not_configured"

    other = GenerationJob.objects.create(kind="chat", status="failed", error={"kind": "x"})
    assert client.post(f"/api/jobs/{other.pk}/retry-narration").status_code == 409


def test_failed_narration_job_records_status_and_hint(
    client: APIClient, fake_edge: type[FakeCommunicate], no_paid_speech: None
) -> None:
    fake_edge.plans = [ConnectionError("offline")] * 5
    job = client.post("/api/narration/preview", {"text": "Hello"}, format="json").json()
    assert job["status"] == "failed"
    assert job["error"]["kind"] == "narration_failed"
    assert job["error"]["provider"] == "edge"
    assert "internet" in job["error"]["message"]


def test_preview_job_records_playable_audio(
    client: APIClient, fake_edge: type[FakeCommunicate], no_paid_speech: None
) -> None:
    response = client.post(
        "/api/narration/preview",
        {"text": "Hello world", "config": {"voice": "en-IE-EmilyNeural", "pitch": 8}},
        format="json",
    )
    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "succeeded", job["error"]
    preview = job["result"]["preview"]
    assert preview["provider"] == "edge"
    assert preview["voice"] == "en-IE-EmilyNeural"
    assert preview["word_timings"] == 2
    assert fake_edge.calls[0]["pitch"] == "+8Hz"
    audio = client.get(preview["url"])
    assert audio.status_code == 200
    assert audio["Content-Type"] == "audio/mpeg"

    too_long = client.post("/api/narration/preview", {"text": "x" * 301}, format="json")
    assert too_long.status_code == 400
    assert client.get(f"/api/narration/previews/{uuid.uuid4()}").status_code == 404


def test_project_override_is_saved_and_cleared(client: APIClient) -> None:
    project = Project.objects.create(title="Calm")
    body = client.patch(
        f"/api/projects/{project.pk}",
        {"narration": {"provider": "edge", "voice": "en-GB-RyanNeural", "voice_label": "Ryan"}},
        format="json",
    ).json()
    assert body["narration"] == {
        "provider": "edge",
        "voice": "en-GB-RyanNeural",
        "voice_label": "Ryan",
    }
    assert body["title"] == "Calm"
    cleared = client.patch(f"/api/projects/{project.pk}", {"narration": None}, format="json").json()
    assert cleared["narration"]["provider"] is None
    blank = client.patch(f"/api/projects/{project.pk}", {"title": "  "}, format="json")
    assert blank.status_code == 400
