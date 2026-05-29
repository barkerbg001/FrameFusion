from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.core.errors import AppError
from app.jobs import store
from app.jobs.models import JobStatus, JobStatusResponse

router = APIRouter()


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str) -> JobStatusResponse:
    job = store.get_job(job_id)
    if job is None:
        raise AppError(
            status_code=404,
            code="job_not_found",
            message=f"Job '{job_id}' was not found",
        )

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


@router.get("/{job_id}/download", response_class=FileResponse)
async def download_job_output(job_id: str) -> FileResponse:
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

    return FileResponse(
        job.output_path,
        media_type=job.media_type or "application/octet-stream",
        filename=job.output_filename or "output",
    )
