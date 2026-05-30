from __future__ import annotations

import tempfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from app.core import config
from app.core.storage import parse_s3_path


def _client():
    return boto3.client(
        "s3",
        endpoint_url=config.S3_ENDPOINT_URL or None,
        aws_access_key_id=config.S3_ACCESS_KEY_ID or None,
        aws_secret_access_key=config.S3_SECRET_ACCESS_KEY or None,
        region_name=config.S3_REGION,
    )


def upload_file(local_path: str, key: str) -> str:
    client = _client()
    client.upload_file(local_path, config.S3_BUCKET, key)
    return f"s3://{config.S3_BUCKET}/{key}"


def download_to_temp(path: str) -> str:
    bucket, key = parse_s3_path(path)
    suffix = Path(key).suffix or ".bin"
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_file.close()
    _client().download_file(bucket, key, temp_file.name)
    return temp_file.name


def delete_object(path: str) -> None:
    bucket, key = parse_s3_path(path)
    try:
        _client().delete_object(Bucket=bucket, Key=key)
    except ClientError:
        raise
