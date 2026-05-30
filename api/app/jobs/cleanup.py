from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from app.core import config
from app.jobs import store
from app.jobs.models import JobStatus

logger = logging.getLogger(__name__)


def cleanup_expired_data() -> dict[str, int]:
    """Remove expired job workspaces and stale files from data directories."""
    cutoff = time.time() - config.CLEANUP_TTL_SECONDS
    removed_workspaces = 0
    removed_files = 0

    for job in store.list_jobs(limit=10_000):
        if job.status not in {JobStatus.COMPLETED, JobStatus.FAILED}:
            continue
        if job.updated_at >= cutoff:
            continue

        workspace = Path(job.workspace_path)
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)
            removed_workspaces += 1

        if job.output_path and not job.output_path.startswith("s3://"):
            output_file = Path(job.output_path)
            if output_file.exists():
                output_file.unlink(missing_ok=True)
                removed_files += 1

    for directory in (config.UPLOADS_DIR, config.OUTPUT_DIR, config.JOBS_DIR):
        removed_files += _cleanup_directory_files(directory, cutoff)

    if removed_workspaces or removed_files:
        logger.info(
            "Cleanup removed %s workspaces and %s files",
            removed_workspaces,
            removed_files,
        )

    return {
        "removed_workspaces": removed_workspaces,
        "removed_files": removed_files,
    }


def _cleanup_directory_files(directory: Path, cutoff: float) -> int:
    if not directory.exists():
        return 0

    removed = 0
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        except OSError:
            logger.exception("Failed to delete expired file %s", path)
    return removed
