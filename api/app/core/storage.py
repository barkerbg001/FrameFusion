from __future__ import annotations

import logging
from pathlib import Path

from app.core import config

logger = logging.getLogger(__name__)


def is_s3_path(path: str) -> bool:
    return path.startswith("s3://")


def parse_s3_path(path: str) -> tuple[str, str]:
    without_scheme = path.removeprefix("s3://")
    bucket, _, key = without_scheme.partition("/")
    if not bucket or not key:
        raise ValueError(f"Invalid S3 path: {path}")
    return bucket, key


def upload_output_if_configured(local_path: str, job_id: str) -> str:
    if config.STORAGE_BACKEND != "s3":
        return local_path

    from app.core.storage_s3 import upload_file

    filename = Path(local_path).name
    key = f"outputs/{job_id}/{filename}"
    return upload_file(local_path, key)


def resolve_download_path(output_path: str) -> str:
    if not is_s3_path(output_path):
        return output_path

    from app.core.storage_s3 import download_to_temp

    return download_to_temp(output_path)


def delete_output_if_present(output_path: str | None) -> None:
    if not output_path:
        return

    if is_s3_path(output_path):
        from app.core.storage_s3 import delete_object

        delete_object(output_path)
        return

    Path(output_path).unlink(missing_ok=True)
