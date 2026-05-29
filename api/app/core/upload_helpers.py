import logging
import os
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from fastapi import UploadFile
from starlette.background import BackgroundTask

from app.core import config
from app.core.errors import AppError
from app.core.request_logging import get_correlation_id
from app.core.upload_validation import save_upload, validate_image_count

logger = logging.getLogger(__name__)

T = TypeVar("T")


def safe_filename(name: str, default: str) -> str:
    cleaned = os.path.basename(name.strip()) or default
    if cleaned in {".", ".."}:
        return default
    return cleaned


def make_temp_workspace() -> tuple[str, BackgroundTask]:
    workspace = tempfile.mkdtemp()
    return workspace, BackgroundTask(shutil.rmtree, workspace, ignore_errors=True)


async def persist_uploaded_images(temp_dir: str, images: list[UploadFile]) -> list[str]:
    validate_image_count(len(images), config.MAX_IMAGE_COUNT)
    image_paths: list[str] = []

    for index, image in enumerate(images):
        image_path = os.path.join(temp_dir, image.filename or f"image_{index}")
        await save_upload(
            image,
            image_path,
            allowed_prefix="image",
            max_bytes=config.MAX_IMAGE_SIZE_BYTES,
            field_name=f"Image {index + 1}",
        )
        image_paths.append(image_path)

    return image_paths


async def persist_uploaded_audio(
    temp_dir: str,
    audio: UploadFile,
    *,
    field_name: str = "Audio",
) -> str:
    audio_path = os.path.join(temp_dir, audio.filename or "audio")
    await save_upload(
        audio,
        audio_path,
        allowed_prefix="audio",
        max_bytes=config.MAX_AUDIO_SIZE_BYTES,
        field_name=field_name,
    )
    return audio_path


async def persist_binary_upload(
    upload: UploadFile,
    dest_path: str,
    *,
    max_bytes: int,
    field_name: str,
) -> None:
    from app.core.upload_validation import CHUNK_SIZE_BYTES

    total = 0
    with open(dest_path, "wb") as dest:
        while True:
            chunk = await upload.read(CHUNK_SIZE_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise AppError(
                    status_code=413,
                    code="file_too_large",
                    message=f"{field_name} exceeds maximum size of {max_bytes} bytes",
                )
            dest.write(chunk)

    if total == 0:
        raise AppError(
            status_code=422,
            code="empty_file",
            message=f"{field_name} is empty",
        )


def run_video_generation(action: Callable[[], T], *, log_message: str) -> T:
    try:
        return action()
    except AppError:
        raise
    except Exception:
        logger.exception(
            log_message,
            extra={"correlation_id": get_correlation_id()},
        )
        raise AppError(
            status_code=500,
            code="internal_error",
            message="An unexpected error occurred while generating the video",
        ) from None


def safe_extract_zip(archive_path: str, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    resolved_destination = destination.resolve()

    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.namelist():
            if member.endswith("/"):
                continue
            target = (destination / member).resolve()
            if not str(target).startswith(str(resolved_destination)):
                raise AppError(
                    status_code=422,
                    code="invalid_archive",
                    message="Channel archive contains unsafe file paths",
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, open(target, "wb") as dest:
                shutil.copyfileobj(source, dest)


def build_zip_archive(video_paths: list[str], zip_path: str) -> str:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for video_path in video_paths:
            archive.write(video_path, arcname=os.path.basename(video_path))
    return zip_path
