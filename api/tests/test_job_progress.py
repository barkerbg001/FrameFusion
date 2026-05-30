from unittest.mock import patch

from app.jobs import store
from fastapi.testclient import TestClient


def test_render_job_reports_intermediate_progress(
    client: TestClient,
    test_image,
    test_audio,
    tmp_path,
):
    output_file = tmp_path / "result.mp4"
    output_file.write_bytes(b"fake-video")
    seen_progress: list[float] = []
    original_update = store.update_job

    def tracking_update(job_id, **kwargs):
        progress = kwargs.get("progress")
        if progress is not None:
            seen_progress.append(progress)
        return original_update(job_id, **kwargs)

    def fake_create_video(**_kwargs):
        from app.jobs.progress import update_render_progress

        update_render_progress(40)
        update_render_progress(80)
        return str(output_file)

    with patch.object(store, "update_job", side_effect=tracking_update):
        with patch(
            "app.jobs.tasks.create_video_from_images_and_audio",
            side_effect=fake_create_video,
        ):
            response = client.post(
                "/api/lofi/generate-video",
                data={"output_name": "result.mp4", "repeat_minutes": "1"},
                files={
                    "images": ("test.png", test_image.read_bytes(), "image/png"),
                    "audio": ("test.wav", test_audio.read_bytes(), "audio/wav"),
                },
            )

    assert response.status_code == 202
    assert any(40 <= progress <= 80 for progress in seen_progress)
    assert seen_progress[-1] == 100
