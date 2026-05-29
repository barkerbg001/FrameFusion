from __future__ import annotations

import os
import random

from moviepy import AudioFileClip, concatenate_videoclips

from app.services.media_utils import (
    image_clip_from_path,
    resolve_resolution,
    trim_audio_to_duration,
    write_video_file,
)


def create_shorts(
    image_paths: list[str],
    output_path: str,
    output_name: str,
    *,
    audio_path: str | None = None,
    seconds_per_image: float = 1.0,
    orientation: str = "portrait",
    shuffle: bool = True,
    max_duration_seconds: float | None = None,
    fps: int = 30,
) -> str:
    if not image_paths:
        raise ValueError("At least one image is required")

    ordered_paths = list(image_paths)
    if shuffle:
        random.shuffle(ordered_paths)

    width, height = resolve_resolution(orientation)
    temp_paths: list[str] = []
    clips = []

    try:
        for image_path in ordered_paths:
            clip, temp_path = image_clip_from_path(
                image_path,
                width=width,
                height=height,
                duration=seconds_per_image,
                fps=fps,
            )
            temp_paths.append(temp_path)
            clips.append(clip)

        video = concatenate_videoclips(clips, method="compose")

        if max_duration_seconds is not None and video.duration > max_duration_seconds:
            video = video.subclipped(0, max_duration_seconds)

        if audio_path is not None:
            audio = trim_audio_to_duration(AudioFileClip(audio_path), video.duration)
            video = video.with_audio(audio)

        output_file = os.path.join(output_path, output_name)
        return write_video_file(video, output_file, fps=fps)
    finally:
        for temp_path in temp_paths:
            if os.path.exists(temp_path):
                os.remove(temp_path)
