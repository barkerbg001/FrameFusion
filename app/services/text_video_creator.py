import os
import random
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:
    from moviepy import AudioFileClip, ImageClip
except ImportError:
    from moviepy.editor import AudioFileClip, ImageClip


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


def create_text_short(
    text: str,
    output_path: str,
    duration_seconds: float = 10,
    background_color: Optional[str] = None,
    text_color: str = "#FFFFFF",
    font_size: int = 96,
) -> str:
    selected_background = background_color or random.choice(BACKGROUND_COLORS)
    frame = _create_text_frame(
        text=text,
        background_color=selected_background,
        text_color=text_color,
        font_size=font_size,
    )
    clip = ImageClip(frame)
    if hasattr(clip, "with_duration"):
        clip = clip.with_duration(duration_seconds).with_fps(30)
    else:
        clip = clip.set_duration(duration_seconds).set_fps(30)

    try:
        write_options = {
            "codec": "libx264",
            "fps": 30,
            "audio": False,
            "preset": "medium",
            "ffmpeg_params": [
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
            ],
            "logger": None,
        }
        clip.write_videofile(
            output_path,
            **write_options,
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
) -> str:
    selected_background = background_color or random.choice(BACKGROUND_COLORS)
    frame = _create_text_frame(
        text=text,
        background_color=selected_background,
        text_color=text_color,
        font_size=font_size,
    )
    audio_clip = AudioFileClip(audio_path)
    video_clip = None

    try:
        if audio_clip.duration <= 0:
            raise ValueError("Audio must have a duration greater than zero")
        if audio_clip.duration > max_duration_seconds:
            raise ValueError(
                f"Audio cannot be longer than {max_duration_seconds:g} seconds"
            )

        video_clip = ImageClip(frame)
        if hasattr(video_clip, "with_duration"):
            video_clip = (
                video_clip
                .with_duration(audio_clip.duration)
                .with_audio(audio_clip)
                .with_fps(30)
            )
        else:
            video_clip = (
                video_clip
                .set_duration(audio_clip.duration)
                .set_audio(audio_clip)
                .set_fps(30)
            )

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
