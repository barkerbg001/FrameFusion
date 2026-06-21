import os
import random
import re
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
MAX_TEXT_SCREENS = 3
TEXT_MARGIN_X = 160
TEXT_MARGIN_Y = 320
TEXT_LINE_SPACING = 24
MIN_SECONDS_PER_SCREEN = 3.0
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


def _max_text_width() -> int:
    return VIDEO_SIZE[0] - TEXT_MARGIN_X


def _max_text_height() -> int:
    return VIDEO_SIZE[1] - TEXT_MARGIN_Y


def _text_block_metrics(
    text: str,
    font_size: int,
) -> tuple[str, float, float]:
    """Return wrapped text, block width, and block height for a 9:16 screen."""
    image = Image.new("RGB", VIDEO_SIZE)
    draw = ImageDraw.Draw(image)
    font = _load_font(font_size)
    wrapped_text = _wrap_text(draw, text, font, max_width=_max_text_width())
    bbox = draw.multiline_textbbox(
        (0, 0),
        wrapped_text,
        font=font,
        spacing=TEXT_LINE_SPACING,
        align="center",
        stroke_width=2,
    )
    return wrapped_text, bbox[2] - bbox[0], bbox[3] - bbox[1]


def text_fits_one_screen(text: str, font_size: int) -> bool:
    _, _, height = _text_block_metrics(text, font_size)
    return height <= _max_text_height()


def split_text_into_screens(
    text: str,
    font_size: int,
    max_screens: int = MAX_TEXT_SCREENS,
) -> list[str]:
    """Split long copy into up to max_screens readable 9:16 text screens."""
    normalized = " ".join(text.strip().split())
    if not normalized:
        return [""]
    if text_fits_one_screen(normalized, font_size):
        return [normalized]
    if max_screens < 2:
        return [normalized]

    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", normalized)
        if sentence.strip()
    ]
    if len(sentences) <= 1:
        sentences = normalized.split()

    screens: list[str] = []
    current = ""

    def flush_current() -> None:
        nonlocal current
        if current.strip():
            screens.append(current.strip())
            current = ""

    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if text_fits_one_screen(candidate, font_size):
            current = candidate
            continue

        flush_current()
        if text_fits_one_screen(sentence, font_size):
            current = sentence
            continue

        words = sentence.split()
        chunk = ""
        for word in words:
            trial = f"{chunk} {word}".strip() if chunk else word
            if text_fits_one_screen(trial, font_size):
                chunk = trial
            else:
                if chunk:
                    screens.append(chunk)
                chunk = word
                if len(screens) >= max_screens:
                    break
        current = chunk
        if len(screens) >= max_screens:
            break

    flush_current()

    if len(screens) > max_screens:
        head = screens[: max_screens - 1]
        tail = " ".join(screens[max_screens - 1 :])
        screens = head + split_text_into_screens(tail, font_size, max_screens=1)
    elif not screens:
        screens = [normalized]

    if len(screens) == 1 and not text_fits_one_screen(screens[0], font_size):
        words = screens[0].split()
        midpoint = max(1, len(words) // 2)
        left = " ".join(words[:midpoint])
        right = " ".join(words[midpoint:])
        if left and right:
            screens = [left, right]

    validated: list[str] = []
    for screen in screens[:max_screens]:
        if text_fits_one_screen(screen, font_size):
            validated.append(screen)
            continue
        words = screen.split()
        chunk = ""
        for word in words:
            trial = f"{chunk} {word}".strip() if chunk else word
            if text_fits_one_screen(trial, font_size):
                chunk = trial
            else:
                if chunk:
                    validated.append(chunk)
                chunk = word
        if chunk:
            validated.append(chunk)

    return validated[:max_screens] if validated else [normalized]


def _screen_durations(total_seconds: float, screen_count: int) -> list[float]:
    if screen_count <= 1:
        return [total_seconds]
    per_screen = max(MIN_SECONDS_PER_SCREEN, total_seconds / screen_count)
    durations = [per_screen] * screen_count
    durations[-1] = max(
        MIN_SECONDS_PER_SCREEN,
        total_seconds - per_screen * (screen_count - 1),
    )
    return durations


def _proportional_screen_durations(
    screens: list[str],
    total_seconds: float,
) -> list[float]:
    if len(screens) <= 1:
        return [total_seconds]
    word_counts = [max(1, len(screen.split())) for screen in screens]
    total_words = sum(word_counts)
    durations = [
        max(MIN_SECONDS_PER_SCREEN, total_seconds * (count / total_words))
        for count in word_counts
    ]
    scale = total_seconds / sum(durations)
    return [duration * scale for duration in durations]


def _create_text_frame(
    text: str,
    background_color: str,
    text_color: str,
    font_size: int,
) -> np.ndarray:
    image = Image.new("RGB", VIDEO_SIZE, background_color)
    draw = ImageDraw.Draw(image)
    max_text_width = VIDEO_SIZE[0] - TEXT_MARGIN_X
    max_text_height = VIDEO_SIZE[1] - TEXT_MARGIN_Y

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
    max_text_width = VIDEO_SIZE[0] - TEXT_MARGIN_X
    max_text_height = VIDEO_SIZE[1] - TEXT_MARGIN_Y

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
    screens = split_text_into_screens(text, font_size)
    screen_durations = _screen_durations(duration_seconds, len(screens))
    selected_background = background_color or random.choice(BACKGROUND_COLORS)
    clips = []

    for screen_text, screen_seconds in zip(screens, screen_durations):
        if background_media_path and background_media_type:
            clip = _compose_short_with_background(
                text=screen_text,
                duration_seconds=screen_seconds,
                background_media_path=background_media_path,
                background_media_type=background_media_type,
                text_color=text_color,
                font_size=font_size,
            )
        else:
            frame = _create_text_frame(
                text=screen_text,
                background_color=selected_background,
                text_color=text_color,
                font_size=font_size,
            )
            clip = ImageClip(frame)
            clip = _set_clip_fps(_set_clip_duration(clip, screen_seconds), 30)
        clips.append(clip)

    final_clip = clips[0] if len(clips) == 1 else concatenate_videoclips(
        clips,
        method="compose",
    )

    try:
        final_clip.write_videofile(
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
        final_clip.close()
        for clip in clips[1:]:
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

        screens = split_text_into_screens(text, font_size)
        screen_durations = _proportional_screen_durations(
            screens,
            audio_clip.duration,
        )
        clips = []
        for screen_text, screen_seconds in zip(screens, screen_durations):
            if background_media_path and background_media_type:
                clip = _compose_short_with_background(
                    text=screen_text,
                    duration_seconds=screen_seconds,
                    background_media_path=background_media_path,
                    background_media_type=background_media_type,
                    text_color=text_color,
                    font_size=font_size,
                )
            else:
                selected_background = background_color or random.choice(
                    BACKGROUND_COLORS
                )
                frame = _create_text_frame(
                    text=screen_text,
                    background_color=selected_background,
                    text_color=text_color,
                    font_size=font_size,
                )
                clip = ImageClip(frame)
                clip = _set_clip_fps(_set_clip_duration(clip, screen_seconds), 30)
            clips.append(clip)

        video_clip = (
            clips[0]
            if len(clips) == 1
            else concatenate_videoclips(clips, method="compose")
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
