from unittest.mock import patch

import pytest
from app.core import config
from fastapi.testclient import TestClient


def assert_api_error(
    response,
    *,
    status: int,
    code: str | None = None,
    message_contains: str | None = None,
) -> dict:
    assert response.status_code == status
    body = response.json()
    assert "error" in body
    assert body["error"]["status"] == status
    if code is not None:
        assert body["error"]["code"] == code
    if message_contains is not None:
        assert message_contains in body["error"]["message"]
    return body["error"]


def test_generate_video_requires_files(client: TestClient):
    response = client.post("/api/lofi/generate-video")

    error = assert_api_error(response, status=422, code="validation_error")
    assert error["details"]
    assert any(item["field"] == "images" for item in error["details"])


def test_generate_video_success(client: TestClient, test_image, test_audio, tmp_path):
    output_file = tmp_path / "result.mp4"
    output_file.write_bytes(b"fake-video")

    with patch(
        "app.routers.lofi.create_video_from_images_and_audio",
        return_value=str(output_file),
    ) as mock_create:
        response = client.post(
            "/api/lofi/generate-video",
            data={
                "output_name": "result.mp4",
                "repeat_minutes": "1",
            },
            files={
                "images": ("test.png", test_image.read_bytes(), "image/png"),
                "audio": ("test.wav", test_audio.read_bytes(), "audio/wav"),
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert response.content == b"fake-video"
    mock_create.assert_called_once()


def test_generate_video_rejects_invalid_image_mime(
    client: TestClient, test_image, test_audio
):
    response = client.post(
        "/api/lofi/generate-video",
        data={"repeat_minutes": "1"},
        files={
            "images": ("test.png", test_image.read_bytes(), "text/plain"),
            "audio": ("test.wav", test_audio.read_bytes(), "audio/wav"),
        },
    )

    assert_api_error(
        response,
        status=422,
        code="invalid_media_type",
        message_contains="image/*",
    )


def test_generate_video_rejects_invalid_audio_mime(
    client: TestClient, test_image, test_audio
):
    response = client.post(
        "/api/lofi/generate-video",
        data={"repeat_minutes": "1"},
        files={
            "images": ("test.png", test_image.read_bytes(), "image/png"),
            "audio": ("test.wav", test_audio.read_bytes(), "application/pdf"),
        },
    )

    assert_api_error(
        response,
        status=422,
        code="invalid_media_type",
        message_contains="audio/*",
    )


def test_generate_video_rejects_too_many_images(
    client: TestClient, test_image, test_audio, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(config, "MAX_IMAGE_COUNT", 2)

    response = client.post(
        "/api/lofi/generate-video",
        data={"repeat_minutes": "1"},
        files=[
            ("images", ("a.png", test_image.read_bytes(), "image/png")),
            ("images", ("b.png", test_image.read_bytes(), "image/png")),
            ("images", ("c.png", test_image.read_bytes(), "image/png")),
            ("audio", ("test.wav", test_audio.read_bytes(), "audio/wav")),
        ],
    )

    assert_api_error(
        response,
        status=422,
        code="too_many_images",
        message_contains="Too many images",
    )


def test_generate_video_rejects_oversized_image(
    client: TestClient, test_image, test_audio, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(config, "MAX_IMAGE_SIZE_BYTES", 32)

    response = client.post(
        "/api/lofi/generate-video",
        data={"repeat_minutes": "1"},
        files={
            "images": ("test.png", test_image.read_bytes(), "image/png"),
            "audio": ("test.wav", test_audio.read_bytes(), "audio/wav"),
        },
    )

    assert_api_error(
        response,
        status=413,
        code="file_too_large",
        message_contains="Image 1",
    )


def test_generate_video_returns_safe_internal_error(client: TestClient, test_image, test_audio):
    with patch(
        "app.routers.lofi.create_video_from_images_and_audio",
        side_effect=RuntimeError("secret encoder failure"),
    ):
        response = client.post(
            "/api/lofi/generate-video",
            data={"repeat_minutes": "1"},
            files={
                "images": ("test.png", test_image.read_bytes(), "image/png"),
                "audio": ("test.wav", test_audio.read_bytes(), "audio/wav"),
            },
        )

    error = assert_api_error(response, status=500, code="internal_error")
    assert "secret encoder failure" not in error["message"]
