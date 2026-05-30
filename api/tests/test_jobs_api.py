import uuid

from app.jobs import store
from app.jobs.models import JobStatus, JobType
from fastapi.testclient import TestClient


def test_list_jobs_returns_recent_jobs(client: TestClient):
    job_id = f"listed-{uuid.uuid4()}"
    store.create_job(
        job_id=job_id,
        job_type=JobType.LOFI,
        workspace_path="/tmp/workspace",
        output_filename="output.mp4",
        media_type="video/mp4",
        payload={},
    )

    response = client.get("/api/jobs?limit=10")
    assert response.status_code == 200
    payload = response.json()
    assert any(job["id"] == job_id for job in payload)


def test_configure_job_webhook(client: TestClient):
    job_id = f"webhook-{uuid.uuid4()}"
    store.create_job(
        job_id=job_id,
        job_type=JobType.LOFI,
        workspace_path="/tmp/workspace",
        output_filename="output.mp4",
        media_type="video/mp4",
        payload={},
    )

    response = client.post(
        f"/api/jobs/{job_id}/webhook",
        json={"url": "https://example.com/hook"},
    )
    assert response.status_code == 200

    job = store.get_job(job_id)
    assert job is not None
    assert job.webhook_url == "https://example.com/hook"


def test_configure_webhook_rejects_completed_job(client: TestClient):
    job_id = f"done-{uuid.uuid4()}"
    store.create_job(
        job_id=job_id,
        job_type=JobType.LOFI,
        workspace_path="/tmp/workspace",
        output_filename="output.mp4",
        media_type="video/mp4",
        payload={},
    )
    store.update_job(job_id, status=JobStatus.COMPLETED, progress=100)

    response = client.post(
        f"/api/jobs/{job_id}/webhook",
        json={"url": "https://example.com/hook"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "job_not_configurable"
