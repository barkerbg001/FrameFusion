import os

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.core.config import RATE_LIMIT_JOB_DOWNLOAD, RATE_LIMIT_JOB_STATUS
from app.core.errors import AppError
from app.core.rate_limit import JOB_DOWNLOAD_SCOPE, limiter
from app.core.storage import resolve_download_path
from app.jobs import store
from app.jobs.models import (
    JobStatus,
    JobStatusResponse,
    JobSummaryResponse,
    JobWebhookRequest,
)

router = APIRouter()


def _to_status_response(job) -> JobStatusResponse:
    return JobStatusResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        progress=job.progress,
        created_at=job.created_at,
        updated_at=job.updated_at,
        output_filename=job.output_filename,
        error=job.error,
    )


def _to_summary_response(job) -> JobSummaryResponse:
    return JobSummaryResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        progress=job.progress,
        created_at=job.created_at,
        updated_at=job.updated_at,
        output_filename=job.output_filename,
        error=job.error,
    )


@router.get("", response_model=list[JobSummaryResponse])
@limiter.limit(RATE_LIMIT_JOB_STATUS)
async def list_jobs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[JobSummaryResponse]:
    jobs = store.list_jobs(limit=limit, offset=offset)
    return [_to_summary_response(job) for job in jobs]


@router.get("/{job_id}", response_model=JobStatusResponse)
@limiter.limit(RATE_LIMIT_JOB_STATUS)
async def get_job_status(request: Request, job_id: str) -> JobStatusResponse:
    job = store.get_job(job_id)
    if job is None:
        raise AppError(
            status_code=404,
            code="job_not_found",
            message=f"Job '{job_id}' was not found",
        )

    return _to_status_response(job)


@router.post("/{job_id}/webhook", response_model=JobStatusResponse)
@limiter.limit(RATE_LIMIT_JOB_STATUS)
async def configure_job_webhook(
    request: Request,
    job_id: str,
    body: JobWebhookRequest,
) -> JobStatusResponse:
    job = store.get_job(job_id)
    if job is None:
        raise AppError(
            status_code=404,
            code="job_not_found",
            message=f"Job '{job_id}' was not found",
        )

    if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
        raise AppError(
            status_code=409,
            code="job_not_configurable",
            message="Webhooks can only be configured for queued or running jobs",
        )

    updated = store.update_job(job_id, webhook_url=str(body.url))
    assert updated is not None
    return _to_status_response(updated)


@router.get("/{job_id}/download", response_class=FileResponse)
@limiter.shared_limit(RATE_LIMIT_JOB_DOWNLOAD, scope=JOB_DOWNLOAD_SCOPE)
async def download_job_output(request: Request, job_id: str) -> FileResponse:
    job = store.get_job(job_id)
    if job is None:
        raise AppError(
            status_code=404,
            code="job_not_found",
            message=f"Job '{job_id}' was not found",
        )

    if job.status != JobStatus.COMPLETED:
        raise AppError(
            status_code=409,
            code="job_not_ready",
            message=f"Job is {job.status.value}; download is available when status is completed",
        )

    if not job.output_path:
        raise AppError(
            status_code=404,
            code="output_missing",
            message="Completed job has no output file",
        )

    download_path = resolve_download_path(job.output_path)
    cleanup: BackgroundTask | None = None
    if download_path != job.output_path:
        cleanup = BackgroundTask(os.unlink, download_path)

    return FileResponse(
        download_path,
        media_type=job.media_type or "application/octet-stream",
        filename=job.output_filename or "output",
        background=cleanup,
    )
