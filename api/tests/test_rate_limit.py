from unittest.mock import patch

import pytest
from app.core.config import RATE_LIMIT_GENERATE
from app.main import app
from fastapi.testclient import TestClient


def _lofi_payload(test_image, test_audio) -> tuple[dict, dict]:
    return (
        {"repeat_minutes": "1"},
        {
            "images": ("test.png", test_image.read_bytes(), "image/png"),
            "audio": ("test.wav", test_audio.read_bytes(), "audio/wav"),
        },
    )


def _parse_limit_per_hour(limit: str) -> int:
    count, window = limit.split("/")
    if window != "hour":
        raise ValueError(f"Test helper only supports hourly limits, got {limit!r}")
    return int(count)


@pytest.mark.rate_limit
def test_generate_endpoint_returns_429_when_limit_exceeded(
    client: TestClient,
    test_image,
    test_audio,
    tmp_path,
):
    limiter = app.state.limiter
    limiter.enabled = True
    limiter.reset()

    output_file = tmp_path / "result.mp4"
    output_file.write_bytes(b"fake-video")
    data, files = _lofi_payload(test_image, test_audio)
    allowed = _parse_limit_per_hour(RATE_LIMIT_GENERATE)

    with patch(
        "app.jobs.tasks.create_video_from_images_and_audio",
        return_value=str(output_file),
    ):
        for _ in range(allowed):
            response = client.post("/api/lofi/generate-video", data=data, files=files)
            assert response.status_code == 202

        response = client.post("/api/lofi/generate-video", data=data, files=files)

    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "rate_limit_exceeded"
    assert body["error"]["status"] == 429


@pytest.mark.rate_limit
def test_generate_limit_is_shared_across_render_types(
    client: TestClient,
    test_image,
    test_audio,
    tmp_path,
):
    limiter = app.state.limiter
    limiter.enabled = True
    limiter.reset()

    output_file = tmp_path / "result.mp4"
    output_file.write_bytes(b"fake-video")
    data, files = _lofi_payload(test_image, test_audio)
    allowed = _parse_limit_per_hour(RATE_LIMIT_GENERATE)

    with patch(
        "app.jobs.tasks.create_video_from_images_and_audio",
        return_value=str(output_file),
    ):
        for _ in range(allowed):
            response = client.post("/api/lofi/generate-video", data=data, files=files)
            assert response.status_code == 202

        response = client.post(
            "/api/slideshow/generate",
            data={"output_name": "slideshow.mp4", "fps": "30", "orientation": "landscape"},
            files=files,
        )

    assert response.status_code == 429


@pytest.mark.rate_limit
def test_health_is_not_rate_limited(client: TestClient):
    limiter = app.state.limiter
    limiter.enabled = True
    limiter.reset()

    for _ in range(20):
        response = client.get("/health")
        assert response.status_code == 200
