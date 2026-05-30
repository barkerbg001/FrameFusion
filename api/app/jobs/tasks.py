import asyncio
import logging
import os
from typing import Any

from app.core import config
from app.core.storage import upload_output_if_configured
from app.core.upload_helpers import run_video_generation
from app.services.e2e_render import render_lofi_e2e
from app.jobs import store
from app.jobs.models import JobStatus, JobType
from app.jobs.progress import (
    bind_render_job,
    clear_render_progress_state,
    unbind_render_job,
    update_render_progress,
)
from app.jobs.webhooks import schedule_job_webhook
from app.services.channel_batch import render_channel_batch
from app.services.shorts import create_shorts
from app.services.slideshow import create_slideshow
from app.services.video_creator import create_video_from_images_and_audio

logger = logging.getLogger(__name__)


async def run_render_job(job_id: str) -> None:
    job = store.get_job(job_id)
    if job is None:
        logger.warning("Render job %s not found", job_id)
        return

    store.update_job(job_id, status=JobStatus.RUNNING, progress=0)
    token = bind_render_job(job_id)

    try:
        update_render_progress(1)
        output_path = await asyncio.to_thread(_execute_job, job.job_type, job.payload)
        stored_output_path = await asyncio.to_thread(
            upload_output_if_configured,
            output_path,
            job_id,
        )
        store.update_job(
            job_id,
            status=JobStatus.COMPLETED,
            progress=100,
            output_path=stored_output_path,
        )
        schedule_job_webhook(job_id)
    except Exception:
        logger.exception("Render job %s failed", job_id)
        store.update_job(
            job_id,
            status=JobStatus.FAILED,
            progress=0,
            error="Video generation failed",
        )
        schedule_job_webhook(job_id)
    finally:
        unbind_render_job(token)
        clear_render_progress_state(job_id)


def _execute_job(job_type: JobType, payload: dict[str, Any]) -> str:
    if job_type == JobType.LOFI and config.E2E_FAST_RENDER:
        return render_lofi_e2e(payload)

    if job_type == JobType.LOFI:
        return run_video_generation(
            lambda: create_video_from_images_and_audio(
                image_paths=list(payload["image_paths"]),
                audio_path=str(payload["audio_path"]),
                output_path=str(payload["output_dir"]),
                output_name=str(payload["output_name"]),
                repeat_minutes=int(payload["repeat_minutes"]),
            ),
            log_message="Lofi video generation failed",
        )

    if job_type == JobType.SLIDESHOW:
        return run_video_generation(
            lambda: create_slideshow(
                image_paths=list(payload["image_paths"]),
                audio_path=str(payload["audio_path"]),
                output_path=str(payload["output_dir"]),
                output_name=str(payload["output_name"]),
                fps=int(payload["fps"]),
                orientation=str(payload["orientation"]),
            ),
            log_message="Slideshow generation failed",
        )

    if job_type == JobType.SHORTS:
        audio_path = payload.get("audio_path")
        return run_video_generation(
            lambda: create_shorts(
                image_paths=list(payload["image_paths"]),
                output_path=str(payload["output_dir"]),
                output_name=str(payload["output_name"]),
                audio_path=str(audio_path) if audio_path else None,
                seconds_per_image=float(payload["seconds_per_image"]),
                orientation=str(payload["orientation"]),
                shuffle=bool(payload["shuffle"]),
                max_duration_seconds=payload.get("max_duration_seconds"),
                fps=int(payload["fps"]),
            ),
            log_message="Shorts generation failed",
        )

    if job_type == JobType.BATCH:
        from app.core.upload_helpers import build_zip_archive

        video_paths = run_video_generation(
            lambda: render_channel_batch(
                channel_root=str(payload["channel_root"]),
                output_root=str(payload["output_dir"]),
                render_type=str(payload["render_type"]),
                audio_path=payload.get("audio_path"),
                orientation=str(payload["orientation"]),
                fps=int(payload["fps"]),
                seconds_per_image=float(payload["seconds_per_image"]),
                max_duration_seconds=payload.get("max_duration_seconds"),
            ),
            log_message="Channel batch generation failed",
        )
        update_render_progress(96)
        zip_path = os.path.join(str(payload["workspace"]), str(payload["zip_name"]))
        result = build_zip_archive(video_paths, zip_path)
        update_render_progress(99)
        return result

    raise ValueError(f"Unsupported job type: {job_type}")


async def render_job(_ctx: dict[str, object], job_id: str) -> None:
    """ARQ worker entrypoint."""
    await run_render_job(job_id)
