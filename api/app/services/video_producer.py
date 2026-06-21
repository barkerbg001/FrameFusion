import os
import uuid
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from app.services.elevenlabs_client import (
    ElevenLabsServiceError,
    generate_speech,
)
from app.services.text_video_creator import (
    create_sound_short,
    create_text_short,
    split_text_into_screens,
)
from app.services.video_creator import create_video_from_images_and_audio


VideoType = Literal["text_short", "sound_short", "lofi"]
GENERATED_DIR = Path(
    os.getenv("FRAMEFUSION_OUTPUT_DIR", "generated")
)


class VideoProducerError(Exception):
    pass


def _optional_text(value: str) -> Optional[str]:
    normalized = value.strip()
    return normalized or None


def _validate_hex_color(value: str, field_name: str) -> Optional[str]:
    normalized = _optional_text(value)
    if normalized is None:
        return None

    color = normalized.upper()
    if len(color) != 7 or not color.startswith("#"):
        raise ValueError(f"{field_name} must use the #RRGGBB format or be blank")
    try:
        int(color[1:], 16)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use the #RRGGBB format") from exc
    return color


def _validate_output_name(output_name: str) -> str:
    normalized = output_name.strip()
    if (
        not normalized
        or normalized != normalized.split("/")[-1]
        or normalized != normalized.split("\\")[-1]
        or not normalized.lower().endswith(".mp4")
    ):
        raise ValueError("output_name must be an .mp4 filename without a path")
    return normalized


def _ensure_generated_dir() -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    return GENERATED_DIR


def _build_output_path(output_name: str) -> Path:
    output_dir = _ensure_generated_dir()
    return output_dir / f"{uuid.uuid4().hex}_{output_name}"


def _get_media_duration(path: str) -> float:
    try:
        from moviepy import VideoFileClip
    except ImportError:
        from moviepy.editor import VideoFileClip

    clip = VideoFileClip(path)
    try:
        return float(clip.duration)
    finally:
        clip.close()


def _build_result(
    video_type: VideoType,
    output_path: Path,
    output_name: str,
    duration_seconds: float,
    background_color: Optional[str] = None,
    narration_audio_path: Optional[str] = None,
    pexels_background: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = {
        "video_type": video_type,
        "output_path": str(output_path.resolve()),
        "output_name": output_name,
        "width": VIDEO_SIZE[0],
        "height": VIDEO_SIZE[1],
        "duration_seconds": duration_seconds,
        "background_color": background_color,
        "narration_audio_path": narration_audio_path,
        "background_source": None,
        "background_media_type": None,
        "background_photographer": None,
        "background_query": None,
    }
    if pexels_background:
        result["background_source"] = "Pexels"
        result["background_media_type"] = pexels_background.get("media_type")
        result["background_photographer"] = pexels_background.get("photographer")
        result["background_query"] = pexels_background.get("query")
    return result


def produce_text_short(
    text: str,
    duration_seconds: float,
    background_color: str,
    text_color: str,
    font_size: int,
    output_name: str,
    pexels_background: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a silent 9:16 text short and return metadata about the output file."""
    normalized_text = _optional_text(text)
    if not normalized_text:
        raise ValueError("text must not be blank")
    if duration_seconds < 1 or duration_seconds > 60:
        raise ValueError("duration_seconds must be between 1 and 60")

    validated_output_name = _validate_output_name(output_name)
    output_path = _build_output_path(validated_output_name)
    selected_background = _validate_hex_color(background_color, "background_color")
    selected_text_color = _validate_hex_color(text_color, "text_color") or "#FFFFFF"

    if font_size < 36 or font_size > 180:
        raise ValueError("font_size must be between 36 and 180")

    try:
        background_media_path = None
        background_media_type = None
        if pexels_background:
            background_media_path = pexels_background["local_path"]
            background_media_type = pexels_background["media_type"]

        create_text_short(
            text=normalized_text,
            output_path=str(output_path),
            duration_seconds=duration_seconds,
            background_color=selected_background,
            text_color=selected_text_color,
            font_size=font_size,
            background_media_path=background_media_path,
            background_media_type=background_media_type,
        )
    except Exception as exc:
        if output_path.exists():
            output_path.unlink()
        raise VideoProducerError(
            f"Unable to create text short: {exc}"
        ) from exc

    return _build_result(
        video_type="text_short",
        output_path=output_path,
        output_name=validated_output_name,
        duration_seconds=duration_seconds,
        background_color=selected_background,
        pexels_background=pexels_background,
    )


def produce_sound_short(
    text: str,
    voice_id: str,
    model_id: str,
    language_code: str,
    background_color: str,
    text_color: str,
    font_size: int,
    output_name: str,
    pexels_background: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a narrated 9:16 short with ElevenLabs audio and centered text."""
    normalized_text = _optional_text(text)
    if not normalized_text:
        raise ValueError("text must not be blank")
    if len(normalized_text) > 2500:
        raise ValueError("text must be 2500 characters or fewer")

    validated_output_name = _validate_output_name(output_name)
    output_path = _build_output_path(validated_output_name)
    audio_path = output_path.with_suffix(".mp3")
    selected_background = _validate_hex_color(background_color, "background_color")
    selected_text_color = _validate_hex_color(text_color, "text_color") or "#FFFFFF"
    selected_voice_id = _optional_text(voice_id)
    selected_model_id = _optional_text(model_id) or "eleven_multilingual_v2"
    selected_language_code = _optional_text(language_code)

    if font_size < 36 or font_size > 180:
        raise ValueError("font_size must be between 36 and 180")

    try:
        generate_speech(
            text=normalized_text,
            output_path=str(audio_path),
            voice_id=selected_voice_id,
            model_id=selected_model_id,
            language_code=selected_language_code,
        )
        background_media_path = None
        background_media_type = None
        if pexels_background:
            background_media_path = pexels_background["local_path"]
            background_media_type = pexels_background["media_type"]

        create_sound_short(
            text=normalized_text,
            audio_path=str(audio_path),
            output_path=str(output_path),
            background_color=selected_background,
            text_color=selected_text_color,
            font_size=font_size,
            background_media_path=background_media_path,
            background_media_type=background_media_type,
        )
    except ElevenLabsServiceError as exc:
        raise VideoProducerError(str(exc)) from exc
    except Exception as exc:
        raise VideoProducerError(
            f"Unable to create sound short: {exc}"
        ) from exc
    finally:
        if audio_path.exists():
            audio_path.unlink()

    duration_seconds = _get_media_duration(str(output_path))
    return _build_result(
        video_type="sound_short",
        output_path=output_path,
        output_name=validated_output_name,
        duration_seconds=duration_seconds,
        background_color=selected_background,
        pexels_background=pexels_background,
    )


def produce_lofi_video(
    image_path: str,
    audio_path: str,
    repeat_minutes: int,
    output_name: str,
) -> Dict[str, Any]:
    """Create a longer lofi-style video from a local image and audio file."""
    normalized_image_path = _optional_text(image_path)
    normalized_audio_path = _optional_text(audio_path)
    if not normalized_image_path:
        raise ValueError("image_path must not be blank")
    if not normalized_audio_path:
        raise ValueError("audio_path must not be blank")

    image_file = Path(normalized_image_path)
    audio_file = Path(normalized_audio_path)
    if not image_file.is_file():
        raise ValueError(f"image_path not found: {normalized_image_path}")
    if not audio_file.is_file():
        raise ValueError(f"audio_path not found: {normalized_audio_path}")
    if repeat_minutes < 1 or repeat_minutes > 180:
        raise ValueError("repeat_minutes must be between 1 and 180")

    validated_output_name = _validate_output_name(output_name)
    output_dir = _ensure_generated_dir()
    session_dir = output_dir / uuid.uuid4().hex
    session_dir.mkdir(parents=True, exist_ok=True)

    try:
        video_path = Path(
            create_video_from_images_and_audio(
                image_paths=[str(image_file.resolve())],
                audio_path=str(audio_file.resolve()),
                output_path=str(session_dir),
                output_name=validated_output_name,
                repeat_minutes=repeat_minutes,
            )
        )
    except Exception as exc:
        raise VideoProducerError(
            f"Unable to create lofi video: {exc}"
        ) from exc

    duration_seconds = _get_media_duration(str(video_path))
    return _build_result(
        video_type="lofi",
        output_path=video_path,
        output_name=validated_output_name,
        duration_seconds=duration_seconds,
    )


DEFAULT_TEXT_COLOR = "#FFFFFF"
DEFAULT_FONT_SIZE = 96
DEFAULT_MODEL_ID = "eleven_multilingual_v2"


def estimate_text_short_duration(text: str, font_size: int = DEFAULT_FONT_SIZE) -> float:
    screens = split_text_into_screens(text, font_size)
    word_count = len(text.split())
    per_screen = max(4.0, min(15.0, word_count / max(len(screens), 1) / 2.5))
    return min(60.0, per_screen * len(screens))


def produce_text_short_simple(
    text: str,
    output_name: str,
    pexels_background: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a silent short using project defaults."""
    return produce_text_short(
        text=text,
        duration_seconds=estimate_text_short_duration(text),
        background_color="",
        text_color=DEFAULT_TEXT_COLOR,
        font_size=DEFAULT_FONT_SIZE,
        output_name=output_name,
        pexels_background=pexels_background,
    )


def produce_sound_short_simple(
    text: str,
    output_name: str,
    pexels_background: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a narrated short using project defaults."""
    return produce_sound_short(
        text=text,
        voice_id="",
        model_id=DEFAULT_MODEL_ID,
        language_code="",
        background_color="",
        text_color=DEFAULT_TEXT_COLOR,
        font_size=DEFAULT_FONT_SIZE,
        output_name=output_name,
        pexels_background=pexels_background,
    )
