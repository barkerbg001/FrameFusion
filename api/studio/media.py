"""Registration of generated media files.

Renderers write into ``FRAMEFUSION_OUTPUT_DIR``. After a job finishes, any media
file it mentions is recorded as a ``MediaAsset``. Files are only ever served through
that record, never by arbitrary path.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from django.db import IntegrityError

from engine.paths import GENERATED_DIR

from .models import GenerationJob, MediaAsset, Project

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def media_kind(file_name: str) -> str | None:
    suffix = Path(file_name).suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return None


def display_name_for(file_name: str) -> str:
    """Generated files are ``<hex>_<name>.ext``; show the readable part."""
    head, sep, tail = file_name.partition("_")
    if sep and len(head) >= 8 and all(c in "0123456789abcdef" for c in head.lower()):
        return tail
    return file_name


PROJECT_FILE = re.compile(r"^projects/[0-9a-f-]{36}/[a-z0-9][a-z0-9-]{0,80}\.(jpg|png|webp)$")


def project_dir(project_id: str) -> Path:
    return GENERATED_DIR / "projects" / str(uuid.UUID(str(project_id)))


def generated_file(file_name: str) -> Path | None:
    """Resolve a stored name to a file inside the output directory, or None.

    Two shapes are allowed: flat ``<name>.ext`` files written by renderers, and
    ``projects/<uuid>/<name>.ext`` images downloaded into a project.
    """
    if not file_name or ".." in file_name or "\\" in file_name:
        return None
    root = GENERATED_DIR.resolve()
    if Path(file_name).name == file_name:
        expected_parent = root
    elif PROJECT_FILE.match(file_name):
        expected_parent = (root / Path(file_name).parent).resolve()
        if not expected_parent.is_relative_to(root):
            return None
    else:
        return None
    path = (root / file_name).resolve()
    if path.parent != expected_parent or not path.is_file():
        return None
    return path


def _candidate_names(value: Any, found: set[str]) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _candidate_names(item, found)
    elif isinstance(value, list | tuple):
        for item in value:
            _candidate_names(item, found)
    elif isinstance(value, str) and len(value) < 1024:
        tail = value.replace("\\", "/").rsplit("/", 1)[-1]
        if media_kind(tail) and "pexels_cache" not in value:
            found.add(tail)


def register_asset(
    file_name: str,
    *,
    project: Project | None = None,
    job: GenerationJob | None = None,
    duration_seconds: float | None = None,
) -> MediaAsset | None:
    kind = media_kind(file_name)
    path = generated_file(file_name)
    if kind is None or path is None:
        return None
    existing = MediaAsset.objects.filter(file_name=file_name).first()
    if existing is not None:
        return existing
    try:
        return MediaAsset.objects.create(
            project=project,
            job=job,
            kind=kind,
            file_name=file_name,
            display_name=display_name_for(file_name),
            duration_seconds=duration_seconds,
            size_bytes=path.stat().st_size,
        )
    except IntegrityError:
        return MediaAsset.objects.filter(file_name=file_name).first()


def register_from_result(job: GenerationJob, result: Any) -> list[MediaAsset]:
    """Register media mentioned in a job result, but only files written during the job."""
    names: set[str] = set()
    _candidate_names(result, names)
    started = job.started_at.timestamp() - 2 if job.started_at else None
    assets = []
    for name in sorted(names):
        path = generated_file(name)
        if path is None:
            continue
        if started is not None and path.stat().st_mtime < started:
            existing = MediaAsset.objects.filter(file_name=name).first()
            if existing is not None:
                assets.append(existing)
            continue
        asset = register_asset(name, project=job.project, job=job)
        if asset is not None:
            assets.append(asset)
    return assets


def asset_url(asset: MediaAsset) -> str:
    return f"/api/media/{asset.pk}/file"


def asset_payload(asset: MediaAsset) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(asset.pk),
        "kind": asset.kind,
        "role": asset.role or None,
        "file_name": asset.file_name,
        "display_name": asset.display_name,
        "url": asset_url(asset),
        "download_url": f"{asset_url(asset)}?download=1",
        "duration_seconds": asset.duration_seconds,
        "size_bytes": asset.size_bytes,
        "project_id": str(asset.project_id) if asset.project_id else None,
        "job_id": str(asset.job_id) if asset.job_id else None,
        "created_at": asset.created_at.isoformat(),
    }
    if asset.kind == "image":
        payload["source"] = {
            "provider": asset.provider or None,
            "title": asset.title or None,
            "source_url": asset.source_url or None,
            "source_page_url": asset.source_page_url or None,
            "creator": asset.creator or None,
            "creator_url": asset.creator_url or None,
            "license": asset.license or "unknown",
            "license_url": asset.license_url or None,
            "attribution": asset.attribution or None,
            "rights_status": asset.rights_status or "unknown",
            "user_supplied": asset.user_supplied,
            "width": asset.width,
            "height": asset.height,
            "checksum": asset.checksum or None,
        }
    return payload
