import os
import random
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:
    from moviepy import AudioFileClip, CompositeVideoClip, ImageClip, VideoFileClip
    from moviepy import concatenate_videoclips
except ImportError:
    from moviepy.editor import (
        AudioFileClip,
        CompositeVideoClip,
        ImageClip,
        VideoFileClip,
        concatenate_videoclips,
    )


VIDEO_SIZE = (1080, 1920)
BACKGROUND_COLORS = (
    "#264653",
    "#2A9D8F",
    "#457B9D",
    "#6D597A",
    "#9B5DE5",
    "#E76F51",
    "#F4A261",
)


def _load_font(font_size: int) -> ImageFont.FreeTypeFont:
    candidates = (
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    )
    for font_path in candidates:
        if os.path.exists(font_path):
            return ImageFont.truetype(font_path, font_size)

    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
    except OSError:
        return ImageFont.load_default()


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    wrapped_lines = []

    for paragraph in text.splitlines() or [text]:
        words = []
        for word in paragraph.split():
            current_part = ""
            for character in word:
                candidate = f"{current_part}{character}"
                bbox = draw.textbbox((0, 0), candidate, font=font)
                if current_part and bbox[2] - bbox[0] > max_width:
                    words.append(current_part)
                    current_part = character
                else:
                    current_part = candidate
            if current_part:
                words.append(current_part)

        if not words:
            wrapped_lines.append("")
            continue

        line = words[0]
        for word in words[1:]:
            candidate = f"{line} {word}"
            bbox = draw.textbbox((0, 0), candidate, font=font)
            if bbox[2] - bbox[0] <= max_width:
                line = candidate
            else:
                wrapped_lines.append(line)
                line = word
        wrapped_lines.append(line)

    return "\n".join(wrapped_lines)


def _create_text_frame(
    text: str,
    background_color: str,
    text_color: str,
    font_size: int,
) -> np.ndarray:
    image = Image.new("RGB", VIDEO_SIZE, background_color)
    draw = ImageDraw.Draw(image)
    max_text_width = VIDEO_SIZE[0] - 160
    max_text_height = VIDEO_SIZE[1] - 320

    for candidate_size in range(max(font_size, 36), 35, -4):
        font = _load_font(candidate_size)
        wrapped_text = _wrap_text(draw, text, font, max_width=max_text_width)
        bbox = draw.multiline_textbbox(
            (0, 0),
            wrapped_text,
            font=font,
            spacing=24,
            align="center",
            stroke_width=2,
        )
        if bbox[3] - bbox[1] <= max_text_height:
            break

    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    position = (
        (VIDEO_SIZE[0] - text_width) / 2,
        (VIDEO_SIZE[1] - text_height) / 2 - bbox[1],
    )

    draw.multiline_text(
        position,
        wrapped_text,
        fill=text_color,
        font=font,
        spacing=24,
        align="center",
        stroke_width=2,
        stroke_fill="#000000",
    )
    return np.asarray(image)


def _create_text_overlay_frame(
    text: str,
    text_color: str,
    font_size: int,
) -> np.ndarray:
    image = Image.new("RGBA", VIDEO_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle([(0, 0), VIDEO_SIZE], fill=(0, 0, 0, 110))
    max_text_width = VIDEO_SIZE[0] - 160
    max_text_height = VIDEO_SIZE[1] - 320

    for candidate_size in range(max(font_size, 36), 35, -4):
        font = _load_font(candidate_size)
        wrapped_text = _wrap_text(draw, text, font, max_width=max_text_width)
        bbox = draw.multiline_textbbox(
            (0, 0),
            wrapped_text,
            font=font,
            spacing=24,
            align="center",
            stroke_width=2,
        )
        if bbox[3] - bbox[1] <= max_text_height:
            break

    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    position = (
        (VIDEO_SIZE[0] - text_width) / 2,
        (VIDEO_SIZE[1] - text_height) / 2 - bbox[1],
    )
    draw.multiline_text(
        position,
        wrapped_text,
        fill=text_color,
        font=font,
        spacing=24,
        align="center",
        stroke_width=2,
        stroke_fill="#000000",
    )
    return np.asarray(image)


def _clip_duration(clip) -> float:
    return float(clip.duration)


def _set_clip_duration(clip, duration_seconds: float):
    if hasattr(clip, "with_duration"):
        return clip.with_duration(duration_seconds)
    return clip.set_duration(duration_seconds)


def _set_clip_fps(clip, fps: int):
    if hasattr(clip, "with_fps"):
        return clip.with_fps(fps)
    return clip.set_fps(fps)


def _subclip(clip, start: float, end: float):
    if hasattr(clip, "subclipped"):
        return clip.subclipped(start, end)
    return clip.subclip(start, end)


def _resize_clip(clip, size: tuple[int, int]):
    if hasattr(clip, "resized"):
        return clip.resized(size)
    return clip.resize(size)


def _crop_clip_center(clip, width: int, height: int):
    if hasattr(clip, "cropped"):
        return clip.cropped(
            x_center=clip.w / 2,
            y_center=clip.h / 2,
            width=width,
            height=height,
        )
    return clip.crop(
        x_center=clip.w / 2,
        y_center=clip.h / 2,
        width=width,
        height=height,
    )


def _fit_background_to_vertical(clip):
    target_w, target_h = VIDEO_SIZE
    scale = max(target_w / clip.w, target_h / clip.h)
    resized = _resize_clip(
        clip,
        (int(clip.w * scale), int(clip.h * scale)),
    )
    return _crop_clip_center(resized, target_w, target_h)


def _loop_background_to_duration(clip, duration_seconds: float):
    if _clip_duration(clip) >= duration_seconds:
        return _subclip(clip, 0, duration_seconds)

    parts = []
    total = 0.0
    while total < duration_seconds:
        parts.append(clip)
        total += _clip_duration(clip)
    looped = concatenate_videoclips(parts, method="compose")
    return _subclip(looped, 0, duration_seconds)


def _load_background_clip(
    background_media_path: str,
    media_type: str,
    duration_seconds: float,
):
    if media_type == "video":
        clip = VideoFileClip(background_media_path)
        fitted = _fit_background_to_vertical(clip)
        return _set_clip_fps(
            _loop_background_to_duration(fitted, duration_seconds),
            30,
        )

    frame = Image.open(background_media_path).convert("RGB")
    fitted = frame.resize(VIDEO_SIZE, Image.Resampling.LANCZOS)
    clip = ImageClip(np.asarray(fitted))
    return _set_clip_fps(_set_clip_duration(clip, duration_seconds), 30)


def load_vertical_media_clip(
    media_path: str,
    media_type: str,
    duration_seconds: float,
):
    """Load a local photo or video as a vertical 9:16 clip."""
    normalized_type = media_type.strip().lower()
    if normalized_type not in {"video", "photo", "image"}:
        raise ValueError("media_type must be video, photo, or image")
    if normalized_type == "image":
        normalized_type = "photo"
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be greater than zero")
    return _load_background_clip(media_path, normalized_type, duration_seconds)


def _compose_short_with_background(
    text: str,
    duration_seconds: float,
    background_media_path: str,
    background_media_type: str,
    text_color: str,
    font_size: int,
    audio_path: Optional[str] = None,
) -> object:
    background = _load_background_clip(
        background_media_path,
        background_media_type,
        duration_seconds,
    )
    overlay_frame = _create_text_overlay_frame(
        text=text,
        text_color=text_color,
        font_size=font_size,
    )
    overlay = ImageClip(overlay_frame, transparent=True)
    overlay = _set_clip_fps(_set_clip_duration(overlay, duration_seconds), 30)
    composed = CompositeVideoClip([background, overlay], size=VIDEO_SIZE)

    if audio_path:
        audio_clip = AudioFileClip(audio_path)
        if hasattr(composed, "with_audio"):
            composed = composed.with_audio(audio_clip)
        else:
            composed = composed.set_audio(audio_clip)

    return composed


def create_text_short(
    text: str,
    output_path: str,
    duration_seconds: float = 10,
    background_color: Optional[str] = None,
    text_color: str = "#FFFFFF",
    font_size: int = 96,
    background_media_path: Optional[str] = None,
    background_media_type: Optional[str] = None,
) -> str:
    clip = None
    if background_media_path and background_media_type:
        clip = _compose_short_with_background(
            text=text,
            duration_seconds=duration_seconds,
            background_media_path=background_media_path,
            background_media_type=background_media_type,
            text_color=text_color,
            font_size=font_size,
        )
    else:
        selected_background = background_color or random.choice(BACKGROUND_COLORS)
        frame = _create_text_frame(
            text=text,
            background_color=selected_background,
            text_color=text_color,
            font_size=font_size,
        )
        clip = ImageClip(frame)
        clip = _set_clip_fps(_set_clip_duration(clip, duration_seconds), 30)

    try:
        clip.write_videofile(
            output_path,
            codec="libx264",
            fps=30,
            audio=False,
            preset="medium",
            ffmpeg_params=[
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
            ],
            logger=None,
        )
    finally:
        clip.close()

    return output_path


def create_sound_short(
    text: str,
    audio_path: str,
    output_path: str,
    background_color: Optional[str] = None,
    text_color: str = "#FFFFFF",
    font_size: int = 96,
    max_duration_seconds: float = 60,
    background_media_path: Optional[str] = None,
    background_media_type: Optional[str] = None,
) -> str:
    audio_clip = AudioFileClip(audio_path)
    video_clip = None

    try:
        if audio_clip.duration <= 0:
            raise ValueError("Audio must have a duration greater than zero")
        if audio_clip.duration > max_duration_seconds:
            raise ValueError(
                f"Audio cannot be longer than {max_duration_seconds:g} seconds"
            )

        if background_media_path and background_media_type:
            video_clip = _compose_short_with_background(
                text=text,
                duration_seconds=audio_clip.duration,
                background_media_path=background_media_path,
                background_media_type=background_media_type,
                text_color=text_color,
                font_size=font_size,
                audio_path=audio_path,
            )
        else:
            selected_background = background_color or random.choice(BACKGROUND_COLORS)
            frame = _create_text_frame(
                text=text,
                background_color=selected_background,
                text_color=text_color,
                font_size=font_size,
            )
            video_clip = ImageClip(frame)
            video_clip = _set_clip_fps(
                _set_clip_duration(video_clip, audio_clip.duration),
                30,
            )
            if hasattr(video_clip, "with_audio"):
                video_clip = video_clip.with_audio(audio_clip)
            else:
                video_clip = video_clip.set_audio(audio_clip)

        video_clip.write_videofile(
            output_path,
            codec="libx264",
            audio_codec="aac",
            fps=30,
            preset="medium",
            ffmpeg_params=[
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
            ],
            logger=None,
        )
    finally:
        if video_clip is not None:
            video_clip.close()
        audio_clip.close()

    return output_path
