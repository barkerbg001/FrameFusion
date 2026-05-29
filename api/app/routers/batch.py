from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile

from app.core.errors import AppError
from app.core.upload_helpers import safe_filename
from app.jobs.models import JobCreateResponse
from app.jobs.submit import submit_batch_job

router = APIRouter()

ZIP_CONTENT_TYPES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
}


@router.post("/channel", status_code=202, response_model=JobCreateResponse)
async def batch_channel(
    background_tasks: BackgroundTasks,
    channel_archive: UploadFile = File(..., description="Zip of subfolders containing images"),
    brand_name: str = Form(...),
    render_type: str = Form("slideshow"),
    audio: UploadFile | None = File(None),
    orientation: str = Form("landscape"),
    fps: int = Form(30),
    seconds_per_image: float = Form(1.0),
    max_duration_seconds: float | None = Form(None),
):
    brand_name = safe_filename(brand_name, "channel")
    if render_type not in {"slideshow", "shorts"}:
        raise AppError(
            status_code=422,
            code="validation_error",
            message="render_type must be 'slideshow' or 'shorts'",
        )

    if channel_archive.content_type not in ZIP_CONTENT_TYPES and not (
        channel_archive.filename or ""
    ).endswith(".zip"):
        raise AppError(
            status_code=422,
            code="invalid_media_type",
            message="Channel archive must be a zip file",
        )

    if render_type == "slideshow" and (audio is None or not audio.filename):
        raise AppError(
            status_code=422,
            code="validation_error",
            message="Audio is required for slideshow batch renders",
        )

    return await submit_batch_job(
        channel_archive=channel_archive,
        brand_name=brand_name,
        render_type=render_type,
        audio=audio,
        orientation=orientation,
        fps=fps,
        seconds_per_image=seconds_per_image,
        max_duration_seconds=max_duration_seconds,
        background_tasks=background_tasks,
    )
