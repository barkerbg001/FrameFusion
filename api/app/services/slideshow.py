from __future__ import annotations

import os

from moviepy import AudioFileClip, concatenate_videoclips

from app.services.media_utils import (
    image_clip_from_path,
    resolve_resolution,
    trim_audio_to_duration,
    write_video_file,
)


def create_slideshow(
    image_paths: list[str],
    audio_path: str,
    output_path: str,
    output_name: str,
    *,
    fps: int = 30,
    orientation: str = "landscape",
    target_duration_seconds: float | None = None,
) -> str:
    if not image_paths:
        raise ValueError("At least one image is required")

    width, height = resolve_resolution(orientation)
    audio = AudioFileClip(audio_path)
    duration = target_duration_seconds if target_duration_seconds is not None else audio.duration
    audio = trim_audio_to_duration(audio, duration)

    per_image_duration = duration / len(image_paths)
    temp_paths: list[str] = []
    clips = []

    try:
        for image_path in image_paths:
            clip, temp_path = image_clip_from_path(
                image_path,
                width=width,
                height=height,
                duration=per_image_duration,
                fps=fps,
            )
            temp_paths.append(temp_path)
            clips.append(clip)

        video = concatenate_videoclips(clips, method="compose").with_audio(audio)
        output_file = os.path.join(output_path, output_name)
        return write_video_file(video, output_file, fps=fps)
    finally:
        for temp_path in temp_paths:
            if os.path.exists(temp_path):
                os.remove(temp_path)
