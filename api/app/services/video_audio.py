import uuid
from pathlib import Path
from typing import Any, Dict

try:
    from moviepy import AudioFileClip, VideoFileClip, concatenate_audioclips
except ImportError:
    from moviepy.editor import AudioFileClip, VideoFileClip, concatenate_audioclips

from app.services.elevenlabs_client import (
    ElevenLabsServiceError,
    generate_speech,
)
from app.services.pexels_footage import PEXELS_CACHE_DIR
from app.services.text_video_creator import VIDEO_SIZE
from app.services.video_producer import DEFAULT_MODEL_ID, GENERATED_DIR


class VideoAudioError(Exception):
    pass


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


def _validate_video_path(video_path: str) -> Path:
    resolved = Path(video_path).resolve()
    generated_root = GENERATED_DIR.resolve()
    if generated_root not in resolved.parents and resolved.parent != generated_root:
        raise ValueError("video_path must be a file in the generated output folder")
    if not resolved.is_file():
        raise FileNotFoundError(f"Video not found: {video_path}")
    if resolved.suffix.lower() != ".mp4":
        raise ValueError("video_path must point to an .mp4 file")
    return resolved


def _validate_audio_path(audio_path: str) -> Path:
    resolved = Path(audio_path).resolve()
    allowed_roots = {
        GENERATED_DIR.resolve(),
        PEXELS_CACHE_DIR.resolve(),
    }
    if not any(
        root == resolved or root in resolved.parents for root in allowed_roots
    ):
        raise ValueError("audio_path must be a local audio file from generated output")
    if not resolved.is_file():
        raise FileNotFoundError(f"Audio not found: {audio_path}")
    if resolved.suffix.lower() not in {".mp3", ".wav", ".m4a", ".aac"}:
        raise ValueError("audio_path must be mp3, wav, m4a, or aac")
    return resolved


def _clip_duration(clip) -> float:
    return float(clip.duration)


def _subclip(clip, start: float, end: float):
    if hasattr(clip, "subclipped"):
        return clip.subclipped(start, end)
    return clip.subclip(start, end)


def _fit_audio_duration(audio_clip, target_duration: float):
    if _clip_duration(audio_clip) >= target_duration:
        return _subclip(audio_clip, 0, target_duration)

    parts = []
    total = 0.0
    while total < target_duration:
        parts.append(audio_clip)
        total += _clip_duration(audio_clip)

    looped = concatenate_audioclips(parts)
    return _subclip(looped, 0, target_duration)


def _attach_audio_to_file(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> None:
    video_clip = VideoFileClip(str(video_path))
    audio_clip = AudioFileClip(str(audio_path))
    fitted_audio = _fit_audio_duration(audio_clip, _clip_duration(video_clip))
    final_clip = None
    try:
        if hasattr(video_clip, "with_audio"):
            final_clip = video_clip.with_audio(fitted_audio)
        else:
            final_clip = video_clip.set_audio(fitted_audio)

        final_clip.write_videofile(
            str(output_path),
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
        if final_clip is not None:
            final_clip.close()
        video_clip.close()
        audio_clip.close()
        if fitted_audio is not audio_clip:
            fitted_audio.close()


def _get_media_duration(path: Path) -> float:
    clip = VideoFileClip(str(path))
    try:
        return _clip_duration(clip)
    finally:
        clip.close()


def _build_result(
    output_path: Path,
    output_name: str,
    source_video_path: Path,
    audio_source: str,
    narration_text: str | None = None,
) -> Dict[str, Any]:
    return {
        "video_type": "video_audio",
        "output_path": str(output_path.resolve()),
        "output_name": output_name,
        "source_video_path": str(source_video_path.resolve()),
        "width": VIDEO_SIZE[0],
        "height": VIDEO_SIZE[1],
        "duration_seconds": _get_media_duration(output_path),
        "audio_source": audio_source,
        "narration_text": narration_text,
    }


def add_narration_to_video(
    video_path: str,
    output_name: str,
    narration_text: str,
) -> Dict[str, Any]:
    """Generate ElevenLabs narration and mux it behind an existing video."""
    validated_name = _validate_output_name(output_name)
    source_video = _validate_video_path(video_path)
    script = narration_text.strip()
    if not script:
        raise ValueError("narration_text must not be blank")
    if len(script) > 2500:
        raise ValueError("narration_text must be 2500 characters or fewer")

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    temp_audio = GENERATED_DIR / f"{uuid.uuid4().hex}_narration.mp3"
    output_path = GENERATED_DIR / f"{uuid.uuid4().hex}_{validated_name}"

    try:
        generate_speech(
            text=script,
            output_path=str(temp_audio),
            voice_id=None,
            model_id=DEFAULT_MODEL_ID,
            language_code=None,
        )
        _attach_audio_to_file(source_video, temp_audio, output_path)
    except ElevenLabsServiceError as exc:
        raise VideoAudioError(str(exc)) from exc
    except OSError as exc:
        raise VideoAudioError(str(exc)) from exc
    except Exception as exc:
        raise VideoAudioError(f"Unable to add narration: {exc}") from exc
    finally:
        if temp_audio.exists():
            temp_audio.unlink()

    if not output_path.is_file():
        raise VideoAudioError("Video with audio was not created")

    return _build_result(
        output_path=output_path,
        output_name=validated_name,
        source_video_path=source_video,
        audio_source="elevenlabs",
        narration_text=script,
    )


def add_audio_file_to_video(
    video_path: str,
    output_name: str,
    audio_path: str,
) -> Dict[str, Any]:
    """Mux an existing audio file behind a video, trimming or looping to fit."""
    validated_name = _validate_output_name(output_name)
    source_video = _validate_video_path(video_path)
    source_audio = _validate_audio_path(audio_path)

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = GENERATED_DIR / f"{uuid.uuid4().hex}_{validated_name}"

    try:
        _attach_audio_to_file(source_video, source_audio, output_path)
    except OSError as exc:
        raise VideoAudioError(str(exc)) from exc
    except Exception as exc:
        raise VideoAudioError(f"Unable to add audio: {exc}") from exc

    if not output_path.is_file():
        raise VideoAudioError("Video with audio was not created")

    return _build_result(
        output_path=output_path,
        output_name=validated_name,
        source_video_path=source_video,
        audio_source="file",
    )
