import filetype
from fastapi import UploadFile

from app.core.errors import AppError

CHUNK_SIZE_BYTES = 1024 * 1024


def validate_media_type(
    content_type: str | None,
    allowed_prefix: str,
    field_name: str,
) -> None:
    if not content_type or not content_type.startswith(f"{allowed_prefix}/"):
        received = content_type or "missing"
        raise AppError(
            status_code=422,
            code="invalid_media_type",
            message=f"{field_name} must be {allowed_prefix}/* (received {received})",
        )


async def save_upload(
    upload: UploadFile,
    dest_path: str,
    *,
    allowed_prefix: str,
    max_bytes: int,
    field_name: str,
) -> None:
    validate_media_type(upload.content_type, allowed_prefix, field_name)

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
                    message=(
                        f"{field_name} exceeds maximum size of "
                        f"{max_bytes} bytes"
                    ),
                )
            dest.write(chunk)

    if total == 0:
        raise AppError(
            status_code=422,
            code="empty_file",
            message=f"{field_name} is empty",
        )

    validate_file_content(dest_path, allowed_prefix, field_name)


def validate_file_content(path: str, allowed_prefix: str, field_name: str) -> None:
    kind = filetype.guess(path)
    if kind is None:
        raise AppError(
            status_code=422,
            code="invalid_media_type",
            message=f"{field_name} has an unrecognized or unsupported file type",
        )
    if not kind.mime.startswith(f"{allowed_prefix}/"):
        raise AppError(
            status_code=422,
            code="invalid_media_type",
            message=(
                f"{field_name} must be {allowed_prefix}/* "
                f"(detected {kind.mime} from file contents)"
            ),
        )


def validate_image_count(image_count: int, max_count: int) -> None:
    if image_count < 1:
        raise AppError(
            status_code=422,
            code="validation_error",
            message="At least one image is required",
        )
    if image_count > max_count:
        raise AppError(
            status_code=422,
            code="too_many_images",
            message=f"Too many images (maximum {max_count})",
        )
