from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager

import cv2
import numpy as np
from moviepy import (
    AudioFileClip,
    ImageClip,
    VideoClip,
    concatenate_audioclips,
)

RESOLUTIONS: dict[str, tuple[int, int]] = {
    "landscape": (1920, 1080),
    "portrait": (1080, 1920),
}


def resolve_resolution(orientation: str) -> tuple[int, int]:
    try:
        return RESOLUTIONS[orientation]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported orientation {orientation!r}. "
            f"Expected one of: {', '.join(RESOLUTIONS)}"
        ) from exc


def load_image_bgr(image_path: str) -> np.ndarray:
    image = cv2.imread(image_path)
    if image is None:
        raise FileNotFoundError(f"Image not found: {image_path}")
    return image


def resize_image(image: np.ndarray, width: int, height: int) -> np.ndarray:
    return cv2.resize(image, (width, height))


@contextmanager
def temp_image_file(image: np.ndarray, suffix: str = ".jpg") -> Iterator[str]:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        path = tmp.name
    cv2.imwrite(path, image)
    try:
        yield path
    finally:
        if os.path.exists(path):
            os.remove(path)


def subclip(clip: VideoClip | AudioFileClip, start: float, end: float):
    return clip.subclipped(start, end)


def loop_audio_to_duration(audio_path: str, target_duration: float) -> AudioFileClip:
    original_audio = AudioFileClip(audio_path)
    repeated: list[AudioFileClip] = []
    duration = 0.0

    while duration + original_audio.duration < target_duration:
        repeated.append(original_audio.copy())
        duration += original_audio.duration

    if duration < target_duration:
        repeated.append(subclip(original_audio, 0, target_duration - duration))

    if not repeated:
        return subclip(original_audio, 0, min(original_audio.duration, target_duration))

    return concatenate_audioclips(repeated)


def trim_audio_to_duration(audio: AudioFileClip, target_duration: float) -> AudioFileClip:
    if audio.duration <= target_duration:
        return audio
    return subclip(audio, 0, target_duration)


def write_video_file(
    clip: VideoClip,
    output_file: str,
    *,
    fps: int = 30,
) -> str:
    from app.jobs.progress import get_encode_progress_range, job_id_ctx, update_render_progress
    from app.services.progress import EncodeProgressLogger

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

    logger: EncodeProgressLogger | None = None
    if job_id_ctx.get() is not None:
        progress_range = get_encode_progress_range()
        logger = EncodeProgressLogger(
            update_render_progress,
            progress_range=progress_range,
        )

    clip.write_videofile(
        output_file,
        codec="libx264",
        audio_codec="aac",
        fps=fps,
        logger=logger,
    )
    return output_file


def image_clip_from_path(
    image_path: str,
    *,
    width: int,
    height: int,
    duration: float,
    fps: int,
) -> tuple[ImageClip, str]:
    """Return an ImageClip and a temp file path the caller must delete."""
    image = resize_image(load_image_bgr(image_path), width, height)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        temp_path = tmp.name
    cv2.imwrite(temp_path, image)
    clip = ImageClip(temp_path).with_duration(duration).with_fps(fps)
    return clip, temp_path
