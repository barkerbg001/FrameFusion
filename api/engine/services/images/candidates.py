"""Image candidates and validated image files."""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from typing import Literal

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

Provider = Literal["pexels", "openverse", "url", "webpage"]
RightsStatus = Literal["documented", "unknown"]

MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000
MIN_SHORT_SIDE = 320
MAX_SIDE = 12_000

UNKNOWN_RIGHTS_NOTE = (
    "Reuse rights are unknown. Only use this image if you own it or have permission."
)


class ImageCandidate(BaseModel):
    """One image found by a search; text fields come from third parties and are untrusted."""

    candidate_id: str
    provider: Provider
    title: str = ""
    preview_url: str | None = None
    download_url: str
    source_page_url: str | None = None
    width: int | None = None
    height: int | None = None
    format: str | None = None
    creator: str | None = None
    creator_url: str | None = None
    license: str = "unknown"
    license_url: str | None = None
    attribution: str | None = None
    rights_status: RightsStatus = "unknown"
    usage_note: str = UNKNOWN_RIGHTS_NOTE
    user_supplied: bool = False
    tags: list[str] = Field(default_factory=list)

    @property
    def orientation(self) -> str | None:
        if not self.width or not self.height:
            return None
        ratio = self.width / self.height
        if ratio < 0.9:
            return "portrait"
        if ratio > 1.1:
            return "landscape"
        return "square"

    def summary(self) -> dict[str, object]:
        """Compact view for model prompts and tool results."""
        return {
            "candidate_id": self.candidate_id,
            "provider": self.provider,
            "title": clean_text(self.title, 120),
            "width": self.width,
            "height": self.height,
            "orientation": self.orientation,
            "creator": clean_text(self.creator or "", 80) or None,
            "license": self.license,
            "rights_status": self.rights_status,
            "source_page_url": self.source_page_url,
        }


_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def clean_text(value: str, limit: int) -> str:
    """Flatten untrusted third-party text so it can't smuggle structure into prompts."""
    text = _CONTROL.sub(" ", str(value or ""))
    text = " ".join(text.replace("<", " ").replace(">", " ").split())
    return text[:limit]


@dataclass
class ValidatedImage:
    data: bytes
    sha256: str
    format: str
    extension: str
    mime: str
    width: int
    height: int

    @property
    def size_bytes(self) -> int:
        return len(self.data)


class InvalidImage(ValueError):
    pass


_FORMATS = {
    "jpeg": ("jpg", "image/jpeg"),
    "png": ("png", "image/png"),
    "webp": ("webp", "image/webp"),
}
# Pillow is held below 12 by moviepy; never let it auto-detect other (riskier) decoders.
PILLOW_FORMATS = ("JPEG", "PNG", "WEBP")


def sniff_format(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def validate_image(data: bytes) -> ValidatedImage:
    """Check magic bytes, decode with Pillow and enforce size and dimension limits."""
    if not data:
        raise InvalidImage("The file is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise InvalidImage("The image is larger than 15 MB.")
    kind = sniff_format(data)
    if kind is None:
        raise InvalidImage("Only JPEG, PNG and WebP images are supported.")
    try:
        with Image.open(io.BytesIO(data), formats=PILLOW_FORMATS) as probe:
            width, height = probe.size
            if width * height > MAX_IMAGE_PIXELS:
                raise InvalidImage("The image has too many pixels.")
            if (probe.format or "").lower() != kind:
                raise InvalidImage("The file contents don't match its image type.")
            probe.verify()
        with Image.open(io.BytesIO(data), formats=PILLOW_FORMATS) as decoded:
            decoded.load()
    except InvalidImage:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        Image.DecompressionBombError,
    ) as exc:
        raise InvalidImage("The image is damaged or could not be decoded.") from exc
    if min(width, height) < MIN_SHORT_SIDE:
        raise InvalidImage(f"The image is too small ({width}x{height}).")
    if max(width, height) > MAX_SIDE:
        raise InvalidImage(f"The image is too large ({width}x{height}).")
    extension, mime = _FORMATS[kind]
    return ValidatedImage(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        format=kind,
        extension=extension,
        mime=mime,
        width=width,
        height=height,
    )


def vertical_fit(width: int, height: int) -> str:
    """How much of the image survives a 9:16 cover crop."""
    target = 9 / 16
    ratio = width / height
    kept = target / ratio if ratio > target else ratio / target
    if kept >= 0.85:
        return "excellent"
    if kept >= 0.5:
        return "good (some cropping)"
    return "poor (heavy side cropping)"


_SAFE_NAME = re.compile(r"[^a-z0-9]+")


def safe_slug(value: str, fallback: str = "image", limit: int = 48) -> str:
    slug = _SAFE_NAME.sub("-", (value or "").lower()).strip("-")[:limit].strip("-")
    return slug or fallback
