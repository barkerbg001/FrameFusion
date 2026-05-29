import os
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse

from app.core import config
from app.core.errors import AppError
from app.core.upload_helpers import (
    build_zip_archive,
    make_temp_workspace,
    persist_binary_upload,
    persist_uploaded_audio,
    run_video_generation,
    safe_extract_zip,
    safe_filename,
)
from app.services.channel_batch import render_channel_batch

router = APIRouter()

ZIP_CONTENT_TYPES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
}


@router.post("/channel", response_class=FileResponse)
async def batch_channel(
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

    workspace, cleanup = make_temp_workspace()
    archive_name = safe_filename(channel_archive.filename or "channel.zip", "channel.zip")
    archive_path = os.path.join(workspace, archive_name)
    await persist_binary_upload(
        channel_archive,
        archive_path,
        max_bytes=config.MAX_AUDIO_SIZE_BYTES * 10,
        field_name="Channel archive",
    )

    if channel_archive.content_type not in ZIP_CONTENT_TYPES and not archive_path.endswith(".zip"):
        raise AppError(
            status_code=422,
            code="invalid_media_type",
            message="Channel archive must be a zip file",
        )

    channel_root = Path(workspace) / "channel"
    safe_extract_zip(archive_path, channel_root)

    audio_path = None
    if audio is not None and audio.filename:
        audio_path = await persist_uploaded_audio(workspace, audio, field_name="Batch audio")
    elif render_type == "slideshow":
        raise AppError(
            status_code=422,
            code="validation_error",
            message="Audio is required for slideshow batch renders",
        )

    output_dir = os.path.join(workspace, "output", brand_name)
    os.makedirs(output_dir, exist_ok=True)

    video_paths = run_video_generation(
        lambda: render_channel_batch(
            channel_root=str(channel_root),
            output_root=output_dir,
            render_type=render_type,
            audio_path=audio_path,
            orientation=orientation,
            fps=fps,
            seconds_per_image=seconds_per_image,
            max_duration_seconds=max_duration_seconds,
        ),
        log_message="Channel batch generation failed",
    )

    zip_name = safe_filename(f"{brand_name}-videos.zip", "channel-videos.zip")
    zip_path = os.path.join(workspace, zip_name)
    build_zip_archive(video_paths, zip_path)

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=zip_name,
        background=cleanup,
    )
