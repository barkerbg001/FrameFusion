from pathlib import Path
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from studio.models import GenerationJob
from tools import handlers

pytestmark = pytest.mark.django_db


def test_text_video_render_runs_as_job(
    client: APIClient, monkeypatch: pytest.MonkeyPatch, output_dir: Path
) -> None:
    def fake_render(job: GenerationJob, data: dict[str, Any]) -> dict[str, Any]:
        path = handlers._output_path(data["output_name"])
        path.write_bytes(b"\x00" * 32)
        return handlers._finish(job, path, {"text": data["text"]})

    monkeypatch.setitem(handlers.RENDERERS, "text_video", fake_render)
    response = client.post(
        "/api/shorts/generate-text-video",
        {"text": "Tide pools at dawn", "output_name": "tides.mp4"},
        format="json",
    )
    assert response.status_code == 202
    job = response.json()
    assert job["kind"] == "render"
    assert job["status"] == "succeeded", job["error"]
    media = job["result"]["media"][0]
    assert media["display_name"] == "tides.mp4"
    assert client.get(media["url"]).status_code == 200


def test_render_validation_errors(client: APIClient) -> None:
    blank = client.post("/api/shorts/generate-text-video", {"text": "   "}, format="json")
    assert blank.status_code == 400
    assert blank.json()["code"] == "validation_error"

    bad_audio = client.post(
        "/api/shorts/generate-audio-video",
        {"text": "Hello", "audio": SimpleUploadedFile("voice.exe", b"MZ")},
        format="multipart",
    )
    assert bad_audio.status_code == 400
    assert bad_audio.json()["code"] == "unsupported_format"

    traversal = client.post(
        "/api/shorts/generate-audio-video",
        {
            "text": "Hello",
            "output_name": "../escape.mp4",
            "audio": SimpleUploadedFile("voice.mp3", b"ID3"),
        },
        format="multipart",
    )
    assert traversal.status_code == 400
    assert not GenerationJob.objects.exists()


def test_failed_render_cleans_up_uploads(
    client: APIClient, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    def broken(job: GenerationJob, data: dict[str, Any]) -> dict[str, Any]:
        assert (handlers.upload_dir(job.pk) / data["audio_file"]).exists()
        raise ValueError("ffmpeg exploded")

    monkeypatch.setitem(handlers.RENDERERS, "audio_video", broken)
    job = client.post(
        "/api/shorts/generate-audio-video",
        {"text": "Hello", "audio": SimpleUploadedFile("voice.mp3", b"ID3")},
        format="multipart",
    ).json()
    assert job["status"] == "failed"
    assert "ffmpeg exploded" in job["error"]["message"]
    assert not (Path(settings.FRAMEFUSION_UPLOAD_DIR) / job["id"]).exists()


def test_tool_start_is_reported_before_the_tool_runs() -> None:
    from engine.agents.base import _json_tool_response
    from engine.runtime import run_context

    events: list[tuple[str, dict[str, Any]]] = []
    with run_context(lambda event, data: events.append((event, data))):
        _json_tool_response("text_short", {}, lambda: events.append(("ran", {})) or {"ok": 1})
    assert [name for name, _ in events] == ["tool_start", "ran", "tool"]
