"""Import data from the pre-Django version of FrameFusion.

Two sources existed before SQLite:

* chats kept in the browser's localStorage (``framefusion:chats``), and
* rendered files in the shared output directory.

Imports are additive and idempotent: projects are keyed by their legacy chat id,
existing projects are never overwritten, and files already registered in the media
library are left alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from django.db import transaction
from pydantic import BaseModel, Field, field_validator

from engine.paths import GENERATED_DIR

from .media import media_kind, register_asset
from .models import MediaAsset, Message, Project


class LegacyAttachment(BaseModel):
    type: str | None = None
    url: str = Field(default="", max_length=2000)
    filename: str | None = Field(default=None, max_length=300)
    duration_seconds: float | None = None


class LegacyMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(default="", max_length=20000)
    attachments: list[LegacyAttachment] = Field(default_factory=list, max_length=20)


class LegacyChat(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(default="Imported chat", max_length=200)
    updatedAt: float | None = None
    titleLocked: bool = False
    messages: list[LegacyMessage] = Field(default_factory=list, max_length=1000)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return " ".join(value.split())[:120] or "Imported chat"


class LegacyImport(BaseModel):
    chats: list[LegacyChat] = Field(max_length=200)


@dataclass
class ImportReport:
    projects_created: int = 0
    projects_skipped: int = 0
    messages_created: int = 0
    media_claimed: int = 0
    media_skipped: int = 0
    skipped_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _file_from_url(url: str) -> str:
    tail = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return tail if media_kind(tail) else ""


def import_chats(data: LegacyImport, *, dry_run: bool = False) -> ImportReport:
    report = ImportReport()
    existing = set(Project.objects.exclude(legacy_id="").values_list("legacy_id", flat=True))
    for chat in data.chats:
        messages = [m for m in chat.messages if m.content.strip() or m.attachments]
        if chat.id in existing or not messages:
            report.projects_skipped += 1
            report.skipped_ids.append(chat.id)
            continue
        report.projects_created += 1
        report.messages_created += len(messages)
        if dry_run:
            continue
        with transaction.atomic():
            project = Project.objects.create(
                title=chat.title,
                title_locked=chat.titleLocked,
                legacy_id=chat.id,
            )
            for message in messages:
                attachments = []
                for attachment in message.attachments:
                    file_name = _file_from_url(attachment.url)
                    asset = MediaAsset.objects.filter(file_name=file_name).first()
                    if asset is None and file_name:
                        asset = register_asset(
                            file_name,
                            project=project,
                            duration_seconds=attachment.duration_seconds,
                        )
                    if asset is None:
                        report.media_skipped += 1
                        continue
                    report.media_claimed += 1
                    attachments.append(
                        {
                            "id": str(asset.pk),
                            "type": asset.kind,
                            "kind": asset.kind,
                            "url": f"/api/media/{asset.pk}/file",
                            "download_url": f"/api/media/{asset.pk}/file?download=1",
                            "filename": asset.display_name,
                            "display_name": asset.display_name,
                            "file_name": asset.file_name,
                            "duration_seconds": attachment.duration_seconds,
                        }
                    )
                Message.objects.create(
                    project=project,
                    role=message.role,
                    content=message.content.strip() or "(attachment)",
                    persona="creative_partner" if message.role == "assistant" else "",
                    attachments=attachments,
                )
            if chat.updatedAt:
                updated = datetime.fromtimestamp(chat.updatedAt / 1000, tz=UTC)
                Project.objects.filter(pk=project.pk).update(updated_at=updated)
        existing.add(chat.id)
    return report


def register_untracked_media(*, dry_run: bool = False) -> ImportReport:
    report = ImportReport()
    if not GENERATED_DIR.is_dir():
        return report
    known = set(MediaAsset.objects.values_list("file_name", flat=True))
    for path in sorted(GENERATED_DIR.iterdir(), key=lambda p: p.stat().st_mtime):
        if not path.is_file() or not media_kind(path.name):
            continue
        if path.name in known:
            report.media_skipped += 1
            continue
        report.media_claimed += 1
        if not dry_run:
            asset = register_asset(path.name)
            if asset is not None:
                created = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
                MediaAsset.objects.filter(pk=asset.pk).update(created_at=created)
    return report
