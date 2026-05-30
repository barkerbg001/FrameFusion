import json
import sqlite3
import time
from typing import Any

from app.core import config
from app.jobs.models import JobRecord, JobStatus, JobType

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    payload TEXT NOT NULL,
    output_path TEXT,
    output_filename TEXT,
    media_type TEXT,
    error TEXT,
    workspace_path TEXT NOT NULL,
    webhook_url TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    config.JOBS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(config.JOBS_DB_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with _connect() as connection:
        connection.executescript(_SCHEMA)
        _ensure_webhook_column(connection)


def _ensure_webhook_column(connection: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
    }
    if "webhook_url" not in columns:
        connection.execute("ALTER TABLE jobs ADD COLUMN webhook_url TEXT")


def create_job(
    *,
    job_id: str,
    job_type: JobType,
    payload: dict[str, Any],
    workspace_path: str,
    output_filename: str,
    media_type: str,
) -> JobRecord:
    now = time.time()
    record = JobRecord(
        id=job_id,
        job_type=job_type,
        status=JobStatus.QUEUED,
        progress=0,
        payload=payload,
        output_filename=output_filename,
        media_type=media_type,
        workspace_path=workspace_path,
        created_at=now,
        updated_at=now,
    )
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO jobs (
                id, job_type, status, progress, payload, output_path,
                output_filename, media_type, error, workspace_path,
                webhook_url, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.job_type.value,
                record.status.value,
                record.progress,
                json.dumps(record.payload),
                record.output_path,
                record.output_filename,
                record.media_type,
                record.error,
                record.workspace_path,
                record.webhook_url,
                record.created_at,
                record.updated_at,
            ),
        )
    return record


def get_job(job_id: str) -> JobRecord | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_jobs(*, limit: int = 50, offset: int = 0) -> list[JobRecord]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM jobs
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    return [_row_to_record(row) for row in rows]


def update_job(
    job_id: str,
    *,
    status: JobStatus | None = None,
    progress: float | None = None,
    output_path: str | None = None,
    error: str | None = None,
    webhook_url: str | None = None,
) -> JobRecord | None:
    existing = get_job(job_id)
    if existing is None:
        return None

    updates: dict[str, object] = {"updated_at": time.time()}
    if status is not None:
        updates["status"] = status
    if progress is not None:
        updates["progress"] = progress
    if output_path is not None:
        updates["output_path"] = output_path
    if error is not None:
        updates["error"] = error
    if webhook_url is not None:
        updates["webhook_url"] = webhook_url

    updated = existing.model_copy(update=updates)

    with _connect() as connection:
        connection.execute(
            """
            UPDATE jobs
            SET status = ?, progress = ?, output_path = ?, error = ?,
                webhook_url = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                updated.status.value,
                updated.progress,
                updated.output_path,
                updated.error,
                updated.webhook_url,
                updated.updated_at,
                job_id,
            ),
        )
    return updated


def _row_to_record(row: sqlite3.Row) -> JobRecord:
    payload = json.loads(row["payload"])
    return JobRecord(
        id=row["id"],
        job_type=JobType(row["job_type"]),
        status=JobStatus(row["status"]),
        progress=row["progress"],
        payload=payload,
        output_path=row["output_path"],
        output_filename=row["output_filename"],
        media_type=row["media_type"],
        error=row["error"],
        workspace_path=row["workspace_path"],
        webhook_url=row["webhook_url"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
