"""Deterministic timeline renderer and quality check.

The renderer turns a validated scene list into a 1080x1920 H.264/AAC MP4: one
cover-cropped photo per scene with a slow pan, a caption band, narration and an
optional quiet music bed. Scenes without an image get a labelled colour card so
a gap is visible instead of silently filled. ``check_video`` re-opens the file
and verifies it before the production is marked complete.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    VideoClip,
    VideoFileClip,
    concatenate_videoclips,
)
from PIL import Image, ImageDraw

from engine.runtime import check_cancelled
from engine.services.text_video_creator import (
    VIDEO_SIZE,
    _create_text_frame,
    _load_font,
    _wrap_text,
    cover_crop_image,
)

FPS = 30
PAN_MARGIN = 1.08
CAPTION_BAND = 760
CAPTION_BOTTOM_MARGIN = 300
PLACEHOLDER_COLORS = ("#1F2933", "#243B53", "#3E4C59")


@dataclass
class TimelineScene:
    duration: float
    caption: str = ""
    image_path: Path | None = None
    placeholder_text: str = ""


@dataclass
class RenderOutcome:
    path: Path
    duration_seconds: float
    has_audio: bool
    placeholder_scenes: list[int] = field(default_factory=list)


def _caption_overlay(text: str) -> tuple[np.ndarray, np.ndarray] | None:
    """RGB and alpha arrays for the bottom caption band, or None without a caption."""
    text = " ".join(text.split())
    if not text:
        return None
    width = VIDEO_SIZE[0]
    band = Image.new("RGBA", (width, CAPTION_BAND), (0, 0, 0, 0))
    gradient = np.linspace(0, 205, CAPTION_BAND, dtype=np.float32)
    alpha = np.repeat(gradient[:, None], width, axis=1)
    shade = Image.fromarray(
        np.dstack([np.zeros_like(alpha)] * 3 + [alpha]).astype(np.uint8), "RGBA"
    )
    band.alpha_composite(shade)
    draw = ImageDraw.Draw(band)
    max_width = width - 160
    for size in range(68, 39, -4):
        font = _load_font(size)
        wrapped = _wrap_text(draw, text, font, max_width=max_width)  # type: ignore[arg-type]
        box = draw.multiline_textbbox(
            (0, 0), wrapped, font=font, spacing=14, align="center", stroke_width=3
        )
        if box[3] - box[1] <= CAPTION_BAND - CAPTION_BOTTOM_MARGIN + 80 and wrapped.count("\n") < 4:
            break
    text_w, text_h = box[2] - box[0], box[3] - box[1]
    position = (
        (width - text_w) / 2 - box[0],
        CAPTION_BAND - CAPTION_BOTTOM_MARGIN - text_h + 60 - box[1],
    )
    draw.multiline_text(
        position,
        wrapped,
        font=font,
        fill="#FFFFFF",
        spacing=14,
        align="center",
        stroke_width=3,
        stroke_fill="#000000",
    )
    array = np.asarray(band).astype(np.float32)
    return array[:, :, :3], array[:, :, 3:4] / 255.0


def _image_clip(path: Path, duration: float, caption: str, index: int) -> VideoClip:
    width, height = VIDEO_SIZE
    big = np.asarray(
        cover_crop_image(str(path), (round(width * PAN_MARGIN), round(height * PAN_MARGIN)))
    )
    span_x, span_y = big.shape[1] - width, big.shape[0] - height
    overlay = _caption_overlay(caption)
    direction = 1 if index % 2 == 0 else -1

    def frame(t: float) -> np.ndarray:
        progress = min(1.0, max(0.0, t / duration)) if duration else 0.0
        eased = progress * progress * (3 - 2 * progress)
        start = 0.0 if direction > 0 else 1.0
        x = round(span_x * (start + direction * eased))
        y = round(span_y * 0.5)
        view = big[y : y + height, x : x + width]
        if overlay is None:
            return view
        rgb, alpha = overlay
        out = view.astype(np.float32)
        out[height - CAPTION_BAND :] = out[height - CAPTION_BAND :] * (1 - alpha) + rgb * alpha
        return out.astype(np.uint8)

    return VideoClip(frame, duration=duration).with_fps(FPS)


def _placeholder_clip(text: str, duration: float, index: int) -> VideoClip:
    still = _create_text_frame(
        text=text or f"Scene {index + 1}",
        background_color=PLACEHOLDER_COLORS[index % len(PLACEHOLDER_COLORS)],
        text_color="#FFFFFF",
        font_size=72,
    )
    return VideoClip(lambda _t: still, duration=duration).with_fps(FPS)


def render_timeline(
    scenes: list[TimelineScene],
    output_path: Path,
    *,
    narration_path: Path | None = None,
    music_path: Path | None = None,
    music_volume: float = 0.14,
) -> RenderOutcome:
    if not scenes:
        raise ValueError("The timeline has no scenes.")
    clips: list[VideoClip] = []
    placeholders: list[int] = []
    for index, scene in enumerate(scenes):
        check_cancelled()
        duration = max(0.5, float(scene.duration))
        if scene.image_path and scene.image_path.is_file():
            clips.append(_image_clip(scene.image_path, duration, scene.caption, index))
        else:
            placeholders.append(index)
            clips.append(
                _placeholder_clip(scene.placeholder_text or scene.caption, duration, index)
            )
    video = concatenate_videoclips(clips, method="chain")
    total = float(video.duration)

    audio_clips: list[Any] = []
    try:
        if narration_path:
            narration = AudioFileClip(str(narration_path))
            audio_clips.append(narration.subclipped(0, min(narration.duration, total)))
        if music_path:
            music = AudioFileClip(str(music_path))
            music = music.subclipped(0, min(music.duration, total)).with_volume_scaled(
                music_volume if narration_path else 0.6
            )
            audio_clips.append(music)
        if audio_clips:
            video = video.with_audio(
                audio_clips[0] if len(audio_clips) == 1 else CompositeAudioClip(audio_clips)
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        check_cancelled()
        video.write_videofile(
            str(output_path),
            codec="libx264",
            audio_codec="aac" if audio_clips else None,
            audio=bool(audio_clips),
            fps=FPS,
            preset="medium",
            ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
            logger=None,
        )
    except BaseException:
        output_path.unlink(missing_ok=True)
        raise
    finally:
        video.close()
        for clip in audio_clips:
            clip.close()
    return RenderOutcome(output_path, total, bool(audio_clips), placeholders)


def _has_audio_stream(path: Path) -> bool:
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
    except ImportError:  # pragma: no cover - moviepy depends on imageio-ffmpeg
        return False
    result = subprocess.run(
        [get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return "Audio:" in result.stderr


def check_video(
    path: Path,
    *,
    expected_seconds: float,
    expect_audio: bool,
    unresolved_scenes: list[int],
) -> dict[str, Any]:
    """Re-open the rendered file and check it can actually be played and downloaded."""
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    exists = path.is_file() and path.stat().st_size > 10_000
    add("file", exists, f"{path.stat().st_size // 1024} KB" if path.is_file() else "missing")
    if exists:
        try:
            with VideoFileClip(str(path)) as clip:
                width, height = clip.size
                duration = float(clip.duration or 0)
            add("resolution", (width, height) == VIDEO_SIZE, f"{width}x{height}")
            add(
                "duration",
                duration > 0
                and abs(duration - expected_seconds) <= max(1.5, expected_seconds * 0.08),
                f"{duration:.1f}s (expected {expected_seconds:.1f}s)",
            )
        except Exception as exc:  # noqa: BLE001 - any decode failure fails QC
            add("decode", False, f"Could not open the video: {type(exc).__name__}")
        if expect_audio:
            has_audio = _has_audio_stream(path)
            add("audio", has_audio, "audio track present" if has_audio else "no audio track")
    add(
        "scene_images",
        not unresolved_scenes,
        "every scene has an image"
        if not unresolved_scenes
        else "placeholder cards in scenes " + ", ".join(str(i + 1) for i in unresolved_scenes),
    )
    blocking = [c for c in checks if not c["ok"] and c["name"] != "scene_images"]
    return {
        "passed": not blocking,
        "checks": checks,
        "problems": [f"{c['name']}: {c['detail']}" for c in checks if not c["ok"]],
    }
