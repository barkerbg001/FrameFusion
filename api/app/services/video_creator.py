from __future__ import annotations

import os

from moviepy import ImageClip

from app.services.media_utils import (
    load_image_bgr,
    loop_audio_to_duration,
    resize_image,
    resolve_resolution,
    temp_image_file,
    write_video_file,
)


def create_video_from_images_and_audio(
    image_paths: list[str],
    audio_path: str,
    output_path: str,
    output_name: str,
    repeat_minutes: int,
    target_duration_seconds: float | None = None,
) -> str:
    if not image_paths:
        raise ValueError("At least one image is required")

    width, height = resolve_resolution("landscape")
    target_duration = (
        target_duration_seconds
        if target_duration_seconds is not None
        else repeat_minutes * 60
    )
    final_audio = loop_audio_to_duration(audio_path, target_duration)

    image = resize_image(load_image_bgr(image_paths[0]), width, height)
    with temp_image_file(image) as resized_path:
        video_clip = (
            ImageClip(resized_path)
            .with_duration(final_audio.duration)
            .with_audio(final_audio)
            .with_fps(30)
        )
        output_file = os.path.join(output_path, output_name)
        return write_video_file(video_clip, output_file, fps=30)
