import os
import uuid

from fastapi import UploadFile
from starlette.background import BackgroundTasks

from app.core import config
from app.core.upload_helpers import (
    persist_binary_upload,
    persist_uploaded_audio,
    persist_uploaded_images,
    safe_extract_zip,
    safe_filename,
)
from app.jobs import store
from app.jobs.models import JobCreateResponse, JobType
from app.jobs.queue import schedule_render_job


async def submit_lofi_job(
    *,
    images: list[UploadFile],
    audio: UploadFile,
    output_name: str,
    repeat_minutes: int,
    background_tasks: BackgroundTasks | None = None,
) -> JobCreateResponse:
    job_id = str(uuid.uuid4())
    workspace = os.path.join(config.JOBS_DIR, job_id)
    os.makedirs(workspace, exist_ok=True)

    image_paths = await persist_uploaded_images(workspace, images)
    audio_path = await persist_uploaded_audio(workspace, audio)
    output_dir = os.path.join(workspace, "output")
    os.makedirs(output_dir, exist_ok=True)

    store.create_job(
        job_id=job_id,
        job_type=JobType.LOFI,
        workspace_path=workspace,
        output_filename=output_name,
        media_type="video/mp4",
        payload={
            "image_paths": image_paths,
            "audio_path": audio_path,
            "output_dir": output_dir,
            "output_name": output_name,
            "repeat_minutes": repeat_minutes,
        },
    )
    await schedule_render_job(job_id, background_tasks)
    return JobCreateResponse(job_id=job_id)


async def submit_slideshow_job(
    *,
    images: list[UploadFile],
    audio: UploadFile,
    output_name: str,
    fps: int,
    orientation: str,
    background_tasks: BackgroundTasks | None = None,
) -> JobCreateResponse:
    job_id = str(uuid.uuid4())
    workspace = os.path.join(config.JOBS_DIR, job_id)
    os.makedirs(workspace, exist_ok=True)

    image_paths = await persist_uploaded_images(workspace, images)
    audio_path = await persist_uploaded_audio(workspace, audio)
    output_dir = os.path.join(workspace, "output")
    os.makedirs(output_dir, exist_ok=True)

    store.create_job(
        job_id=job_id,
        job_type=JobType.SLIDESHOW,
        workspace_path=workspace,
        output_filename=output_name,
        media_type="video/mp4",
        payload={
            "image_paths": image_paths,
            "audio_path": audio_path,
            "output_dir": output_dir,
            "output_name": output_name,
            "fps": fps,
            "orientation": orientation,
        },
    )
    await schedule_render_job(job_id, background_tasks)
    return JobCreateResponse(job_id=job_id)


async def submit_shorts_job(
    *,
    images: list[UploadFile],
    audio: UploadFile | None,
    output_name: str,
    seconds_per_image: float,
    orientation: str,
    shuffle: bool,
    max_duration_seconds: float | None,
    fps: int,
    background_tasks: BackgroundTasks | None = None,
) -> JobCreateResponse:
    job_id = str(uuid.uuid4())
    workspace = os.path.join(config.JOBS_DIR, job_id)
    os.makedirs(workspace, exist_ok=True)

    image_paths = await persist_uploaded_images(workspace, images)
    audio_path = None
    if audio is not None and audio.filename:
        audio_path = await persist_uploaded_audio(workspace, audio)

    output_dir = os.path.join(workspace, "output")
    os.makedirs(output_dir, exist_ok=True)

    store.create_job(
        job_id=job_id,
        job_type=JobType.SHORTS,
        workspace_path=workspace,
        output_filename=output_name,
        media_type="video/mp4",
        payload={
            "image_paths": image_paths,
            "audio_path": audio_path,
            "output_dir": output_dir,
            "output_name": output_name,
            "seconds_per_image": seconds_per_image,
            "orientation": orientation,
            "shuffle": shuffle,
            "max_duration_seconds": max_duration_seconds,
            "fps": fps,
        },
    )
    await schedule_render_job(job_id, background_tasks)
    return JobCreateResponse(job_id=job_id)


async def submit_batch_job(
    *,
    channel_archive: UploadFile,
    brand_name: str,
    render_type: str,
    audio: UploadFile | None,
    orientation: str,
    fps: int,
    seconds_per_image: float,
    max_duration_seconds: float | None,
    background_tasks: BackgroundTasks | None = None,
) -> JobCreateResponse:
    from pathlib import Path

    job_id = str(uuid.uuid4())
    workspace = os.path.join(config.JOBS_DIR, job_id)
    os.makedirs(workspace, exist_ok=True)

    archive_name = safe_filename(channel_archive.filename or "channel.zip", "channel.zip")
    archive_path = os.path.join(workspace, archive_name)
    await persist_binary_upload(
        channel_archive,
        archive_path,
        max_bytes=config.MAX_AUDIO_SIZE_BYTES * 10,
        field_name="Channel archive",
    )

    channel_root = Path(workspace) / "channel"
    safe_extract_zip(archive_path, channel_root)

    audio_path = None
    if audio is not None and audio.filename:
        audio_path = await persist_uploaded_audio(workspace, audio, field_name="Batch audio")

    output_dir = os.path.join(workspace, "output", brand_name)
    os.makedirs(output_dir, exist_ok=True)
    zip_name = safe_filename(f"{brand_name}-videos.zip", "channel-videos.zip")

    store.create_job(
        job_id=job_id,
        job_type=JobType.BATCH,
        workspace_path=workspace,
        output_filename=zip_name,
        media_type="application/zip",
        payload={
            "channel_root": str(channel_root),
            "output_dir": output_dir,
            "render_type": render_type,
            "audio_path": audio_path,
            "orientation": orientation,
            "fps": fps,
            "seconds_per_image": seconds_per_image,
            "max_duration_seconds": max_duration_seconds,
            "workspace": workspace,
            "zip_name": zip_name,
        },
    )
    await schedule_render_job(job_id, background_tasks)
    return JobCreateResponse(job_id=job_id)
