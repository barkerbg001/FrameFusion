import io
import zipfile
from unittest.mock import patch

from fastapi.testclient import TestClient


def test_slideshow_generate_success(client: TestClient, test_image, test_audio, tmp_path):
    output_file = tmp_path / "slideshow.mp4"
    output_file.write_bytes(b"slideshow-video")

    with patch(
        "app.routers.slideshow.create_slideshow",
        return_value=str(output_file),
    ):
        response = client.post(
            "/api/slideshow/generate",
            data={"output_name": "slideshow.mp4", "fps": "30", "orientation": "landscape"},
            files={
                "images": ("test.png", test_image.read_bytes(), "image/png"),
                "audio": ("test.wav", test_audio.read_bytes(), "audio/wav"),
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert response.content == b"slideshow-video"


def test_shorts_generate_success(client: TestClient, test_image, tmp_path):
    output_file = tmp_path / "shorts.mp4"
    output_file.write_bytes(b"shorts-video")

    with patch(
        "app.routers.shorts.create_shorts",
        return_value=str(output_file),
    ):
        response = client.post(
            "/api/shorts/generate",
            data={
                "output_name": "shorts.mp4",
                "seconds_per_image": "1",
                "orientation": "portrait",
                "shuffle": "false",
                "fps": "30",
            },
            files={
                "images": ("test.png", test_image.read_bytes(), "image/png"),
            },
        )

    assert response.status_code == 200
    assert response.content == b"shorts-video"


def test_batch_channel_requires_audio_for_slideshow(client: TestClient, test_image):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("clip-a/frame.png", test_image.read_bytes())
    archive.seek(0)

    response = client.post(
        "/api/batch/channel",
        data={"brand_name": "demo", "render_type": "slideshow"},
        files={"channel_archive": ("channel.zip", archive.read(), "application/zip")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_batch_channel_returns_zip(client: TestClient, test_image, test_audio, tmp_path):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("clip-a/frame.png", test_image.read_bytes())
    archive.seek(0)

    video_file = tmp_path / "clip-a.mp4"
    video_file.write_bytes(b"clip-video")

    with patch(
        "app.routers.batch.render_channel_batch",
        return_value=[str(video_file)],
    ):
        response = client.post(
            "/api/batch/channel",
            data={"brand_name": "demo", "render_type": "shorts"},
            files={
                "channel_archive": ("channel.zip", archive.read(), "application/zip"),
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.content.startswith(b"PK")
