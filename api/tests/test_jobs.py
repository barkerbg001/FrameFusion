import uuid
from unittest.mock import patch

from app.jobs import store
from app.jobs.models import JobStatus, JobType
from fastapi.testclient import TestClient

from tests.conftest import wait_for_job


def test_get_job_not_found(client: TestClient):
    response = client.get("/api/jobs/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"


def test_download_job_not_ready(client: TestClient):
    job_id = f"queued-job-{uuid.uuid4()}"
    job = store.create_job(
        job_id=job_id,
        job_type=JobType.LOFI,
        workspace_path="/tmp/workspace",
        output_filename="output.mp4",
        media_type="video/mp4",
        payload={},
    )
    assert job.status == JobStatus.QUEUED

    response = client.get(f"/api/jobs/{job_id}/download")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "job_not_ready"


def test_job_status_and_download_flow(client: TestClient, test_image, test_audio, tmp_path):
    output_file = tmp_path / "result.mp4"
    output_file.write_bytes(b"rendered-video")

    with patch(
        "app.jobs.tasks.create_video_from_images_and_audio",
        return_value=str(output_file),
    ):
        create_response = client.post(
            "/api/lofi/generate-video",
            data={"output_name": "result.mp4", "repeat_minutes": "1"},
            files={
                "images": ("test.png", test_image.read_bytes(), "image/png"),
                "audio": ("test.wav", test_audio.read_bytes(), "audio/wav"),
            },
        )

    assert create_response.status_code == 202
    job_id = create_response.json()["job_id"]

    status_payload = wait_for_job(client, job_id)
    assert status_payload["status"] == "completed"
    assert status_payload["progress"] == 100
    assert status_payload["output_filename"] == "result.mp4"

    download = client.get(f"/api/jobs/{job_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "video/mp4"
    assert download.content == b"rendered-video"
