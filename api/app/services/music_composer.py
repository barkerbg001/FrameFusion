import os
import uuid
from pathlib import Path
from typing import Any, Dict, Literal

try:
    from moviepy import AudioFileClip
except ImportError:
    from moviepy.editor import AudioFileClip

from dotenv import load_dotenv

from app.services.elevenlabs_client import (
    ElevenLabsServiceError,
    generate_music,
)
from app.services.output_filename import resolve_music_output_name
from app.services.procedural_music import generate_procedural_music
from app.services.video_producer import GENERATED_DIR


MusicProvider = Literal["elevenlabs", "procedural"]


class MusicComposerError(Exception):
    pass


def _audio_duration_seconds(path: Path) -> float:
    clip = AudioFileClip(str(path))
    try:
        return float(clip.duration)
    finally:
        clip.close()


def _resolve_provider() -> MusicProvider:
    load_dotenv()
    explicit = os.getenv("MUSIC_PROVIDER", "").strip().lower()
    if explicit in {"elevenlabs", "procedural"}:
        return explicit  # type: ignore[return-value]
    if os.getenv("ELEVENLABS_API_KEY"):
        return "elevenlabs"
    return "procedural"


def compose_music(
    prompt: str,
    duration_seconds: int = 30,
    output_name: str | None = None,
    force_instrumental: bool = True,
) -> Dict[str, Any]:
    """Generate background music and return metadata about the saved file."""
    normalized_prompt = " ".join(prompt.strip().split())
    if len(normalized_prompt) < 3:
        raise ValueError("prompt must contain at least three characters")

    clamped_seconds = max(3, min(duration_seconds, 600))
    validated_name = output_name or resolve_music_output_name(
        normalized_prompt,
        default_stem="track",
    )
    if not validated_name.lower().endswith((".mp3", ".wav")):
        raise ValueError("output_name must end with .mp3 or .wav")

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    provider = _resolve_provider()
    extension = ".mp3" if provider == "elevenlabs" else ".wav"
    if validated_name.lower().endswith(".mp3") and provider == "procedural":
        validated_name = f"{Path(validated_name).stem}.wav"

    temp_stem = f"{uuid.uuid4().hex}_{Path(validated_name).stem}{extension}"
    output_path = GENERATED_DIR / temp_stem
    limitations: list[str] = []

    try:
        if provider == "elevenlabs":
            generate_music(
                prompt=normalized_prompt,
                output_path=str(output_path),
                duration_seconds=clamped_seconds,
                force_instrumental=force_instrumental,
            )
        else:
            generate_procedural_music(
                prompt=normalized_prompt,
                output_path=str(output_path),
                duration_seconds=clamped_seconds,
            )
            limitations.append(
                "Generated with FrameFusion's free procedural composer. "
                "Set ELEVENLABS_API_KEY for studio-grade ElevenLabs Music."
            )
    except ElevenLabsServiceError as exc:
        if provider != "elevenlabs":
            raise MusicComposerError(str(exc)) from exc
        fallback_path = GENERATED_DIR / f"{uuid.uuid4().hex}_{Path(validated_name).stem}.wav"
        generate_procedural_music(
            prompt=normalized_prompt,
            output_path=str(fallback_path),
            duration_seconds=clamped_seconds,
        )
        output_path = fallback_path
        provider = "procedural"
        limitations.append(
            f"ElevenLabs music failed ({exc}). Used procedural fallback instead."
        )

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise MusicComposerError("Music file was not created")

    duration = _audio_duration_seconds(output_path)
    return {
        "audio_type": "music",
        "provider": provider,
        "output_path": str(output_path.resolve()),
        "output_name": validated_name,
        "prompt": normalized_prompt,
        "duration_seconds": duration,
        "force_instrumental": force_instrumental,
        "limitations": limitations,
    }
