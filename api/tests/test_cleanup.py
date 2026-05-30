import sqlite3
import time

from app.core import config
from app.jobs import store
from app.jobs.cleanup import cleanup_expired_data
from app.jobs.models import JobStatus, JobType


def test_cleanup_removes_expired_job_workspace(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    jobs_db = tmp_path / "jobs.db"
    workspace = jobs_dir / "old-job"
    workspace.mkdir(parents=True)
    (workspace / "input.png").write_bytes(b"x")

    monkeypatch.setattr(config, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(config, "JOBS_DB_PATH", jobs_db)
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "CLEANUP_TTL_SECONDS", 60)
    store.init_db()

    store.create_job(
        job_id="old-job",
        job_type=JobType.LOFI,
        workspace_path=str(workspace),
        output_filename="output.mp4",
        media_type="video/mp4",
        payload={},
    )
    store.update_job("old-job", status=JobStatus.COMPLETED, progress=100)

    with sqlite3.connect(config.JOBS_DB_PATH) as connection:
        connection.execute(
            "UPDATE jobs SET updated_at = ? WHERE id = ?",
            (time.time() - 3600, "old-job"),
        )

    result = cleanup_expired_data()

    assert result["removed_workspaces"] == 1
    assert not workspace.exists()
