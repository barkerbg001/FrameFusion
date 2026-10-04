"""Renderer-ready 9:16 variants derived from original images.

Originals are never modified. When a plain cover crop would keep most of the
image, the original is used as is (the renderer crops and pans it). When it
would cut away most of the frame (wide landscapes, diagrams), a derived file is
written next to the original: the whole image fitted to the width over a
blurred, darkened copy of itself, so the subject is never cropped out or
stretched. EXIF orientation is applied in both cases.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from engine.services.images.candidates import PILLOW_FORMATS

FRAME = (1080, 1920)
MIN_KEPT_FRACTION = 0.6
VARIANT_SUFFIX = ".render.jpg"


def kept_fraction(width: int, height: int) -> float:
    target = FRAME[0] / FRAME[1]
    ratio = width / height
    return target / ratio if ratio > target else ratio / target


def compose_contained(image: Image.Image) -> Image.Image:
    frame_w, frame_h = FRAME
    background = ImageOps.fit(image, FRAME, Image.Resampling.LANCZOS)
    background = background.filter(ImageFilter.GaussianBlur(40))
    background = Image.blend(background, Image.new("RGB", FRAME, (0, 0, 0)), 0.45)
    scale = min(frame_w / image.width, (frame_h * 0.72) / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    foreground = image.resize(size, Image.Resampling.LANCZOS)
    top = round((frame_h - size[1]) * 0.42)
    background.paste(foreground, ((frame_w - size[0]) // 2, top))
    return background


def render_variant(original: Path) -> Path:
    """Return the file the renderer should use for ``original`` (creating it if needed)."""
    variant = original.with_name(original.stem + VARIANT_SUFFIX)
    if variant.is_file() and variant.stat().st_mtime >= original.stat().st_mtime:
        return variant
    with Image.open(original, formats=PILLOW_FORMATS) as source:
        rotated = ImageOps.exif_transpose(source)
        needs_rotation = rotated.size != source.size or source.getexif().get(0x0112, 1) != 1
        image = rotated.convert("RGB")
    if kept_fraction(image.width, image.height) >= MIN_KEPT_FRACTION and not needs_rotation:
        return original
    composed = (
        image
        if kept_fraction(image.width, image.height) >= MIN_KEPT_FRACTION
        else compose_contained(image)
    )
    handle, temp_name = tempfile.mkstemp(dir=original.parent, suffix=".part")
    try:
        with os.fdopen(handle, "wb") as out:
            composed.save(out, format="JPEG", quality=90)
        os.replace(temp_name, variant)
    finally:
        Path(temp_name).unlink(missing_ok=True)
    return variant
