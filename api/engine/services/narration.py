"""One entry point for narration (text-to-speech), whichever provider is selected.

Providers:

- ``edge``: free, no API key, online (``engine.services.edge_tts_client``).
- ``elevenlabs``: paid, uses the encrypted ElevenLabs key (``elevenlabs_client``).

The provider comes from Settings → Narration, optionally overridden per project. A
failure is raised as ``NarrationError``; nothing ever switches to another provider on
its own, so a free request can never turn into a paid one.
"""

from __future__ import annotations

import contextvars
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from engine import integrations
from engine.runtime import check_cancelled

Provider = Literal["edge", "elevenlabs"]
PROVIDERS: tuple[Provider, ...] = ("edge", "elevenlabs")
PROVIDER_LABELS: dict[str, str] = {"edge": "Edge TTS (free)", "elevenlabs": "ElevenLabs"}
SETTINGS_HINT = "Retry, or choose another voice or provider in Settings → Narration."

_project_override: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "framefusion_narration_override", default=None
)


class NarrationError(Exception):
    def __init__(self, message: str, *, provider: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.retryable = retryable


class NarrationStageError(Exception):
    """Narration failed after the script and visuals were ready.

    ``render_spec`` holds everything needed to retry just the narrated render, so a
    retry doesn't regenerate the script, research or footage.
    """

    abort_run = True

    def __init__(self, message: str, render_spec: dict[str, Any]) -> None:
        super().__init__(message)
        self.render_spec = render_spec


@dataclass
class NarrationConfig:
    provider: Provider
    voice: str = ""
    voice_label: str = ""
    rate: int = 0
    pitch: int = 0
    volume: int = 0
    source: Literal["default", "project", "request"] = "default"

    @property
    def label(self) -> str:
        return PROVIDER_LABELS[self.provider]

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "provider_label": self.label}


@dataclass
class NarrationResult:
    path: Path
    provider: Provider
    voice: str
    duration_seconds: float
    words: list[tuple[float, float, str]] = field(default_factory=list)
    sentences: list[tuple[float, float, str]] = field(default_factory=list)
    normalized: bool = False

    def metadata(self) -> dict[str, Any]:
        return {
            "narration_provider": self.provider,
            "narration_voice": self.voice,
            "narration_duration_seconds": round(self.duration_seconds, 2),
            "narration_word_timings": len(self.words),
            "narration_normalized": self.normalized,
        }


@contextmanager
def project_override(provider: str, voice: str = "", voice_label: str = "") -> Iterator[None]:
    """Apply a project's narration override for the duration of a job."""
    token = _project_override.set(
        {"provider": provider, "voice": voice, "voice_label": voice_label} if provider else None
    )
    try:
        yield
    finally:
        _project_override.reset(token)


def _coerce_provider(value: Any) -> Provider:
    return cast(Provider, value) if value in PROVIDERS else "edge"


def config_from(saved: dict[str, Any], provider: str | None = None) -> NarrationConfig:
    selected = _coerce_provider(provider or saved.get("provider"))
    if selected == "edge":
        edge = saved.get("edge") or {}
        return NarrationConfig(
            provider="edge",
            voice=str(edge.get("voice") or ""),
            voice_label=str(edge.get("voice_label") or ""),
            rate=int(edge.get("rate") or 0),
            pitch=int(edge.get("pitch") or 0),
            volume=int(edge.get("volume") or 0),
        )
    eleven = saved.get("elevenlabs") or {}
    return NarrationConfig(
        provider="elevenlabs",
        voice=str(eleven.get("voice_id") or ""),
        voice_label=str(eleven.get("voice_name") or ""),
    )


def default_config(provider: str | None = None) -> NarrationConfig:
    """The saved default from Settings → Narration, ignoring any project override."""
    return config_from(integrations.get_settings("narration"), provider)


def current_config() -> NarrationConfig:
    """Saved default, with the active project's override applied on top."""
    saved = integrations.get_settings("narration")
    override = _project_override.get()
    if not override:
        return config_from(saved)
    config = config_from(saved, override["provider"])
    if override.get("voice"):
        config.voice = override["voice"]
        config.voice_label = override.get("voice_label", "")
    config.source = "project"
    return config


def readiness(config: NarrationConfig | None = None) -> dict[str, Any]:
    config = config or current_config()
    problem = None
    if config.provider == "elevenlabs" and not integrations.is_configured("elevenlabs"):
        problem = (
            "Narration is set to ElevenLabs, but no ElevenLabs API key is saved. Add one in "
            "Settings → Narration, or switch to the free Edge TTS provider."
        )
    return {
        "provider": config.provider,
        "provider_label": config.label,
        "voice": config.voice,
        "voice_label": config.voice_label,
        "ready": problem is None,
        "problem": problem,
        "online": True,
        "requires_key": config.provider == "elevenlabs",
        "source": config.source,
    }


def is_ready() -> bool:
    return bool(readiness()["ready"])


def unavailable_note() -> str:
    return str(readiness()["problem"] or "")


def audio_duration(path: Path) -> float:
    try:
        from moviepy import AudioFileClip
    except ImportError:  # pragma: no cover - moviepy 1.x
        from moviepy.editor import AudioFileClip

    clip = AudioFileClip(str(path))
    try:
        return float(clip.duration or 0)
    finally:
        clip.close()


def normalize_loudness(path: Path) -> bool:
    """Normalise speech to about -16 LUFS so voices from either provider sit at one level.

    Timing is unchanged, so word timings stay valid. Returns ``False`` and keeps the
    original file if ffmpeg is unavailable or fails.
    """
    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - normalisation is best effort
        return False
    normalized = path.with_name(f"{path.stem}.norm.mp3")
    try:
        completed = subprocess.run(
            [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(path),
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-b:a", "160k",
                str(normalized),
            ],
            capture_output=True,
            timeout=120,
            check=False,
        )  # fmt: skip
        if completed.returncode != 0 or not normalized.is_file():
            return False
        normalized.replace(path)
        return True
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        normalized.unlink(missing_ok=True)


def _edge(text: str, output_path: Path, config: NarrationConfig) -> NarrationResult:
    from engine.services import edge_tts_client

    try:
        speech = edge_tts_client.synthesize(
            text,
            output_path,
            voice=config.voice or edge_tts_client.DEFAULT_VOICE,
            rate=config.rate,
            pitch=config.pitch,
            volume=config.volume,
        )
    except edge_tts_client.EdgeTTSError as exc:
        raise NarrationError(str(exc), provider="edge", retryable=exc.retryable) from exc
    return NarrationResult(
        path=output_path,
        provider="edge",
        voice=speech.voice,
        duration_seconds=0.0,
        words=speech.words,
        sentences=speech.sentences,
    )


def _elevenlabs(text: str, output_path: Path, config: NarrationConfig) -> NarrationResult:
    from engine.services.elevenlabs_client import (
        DEFAULT_VOICE_ID,
        ElevenLabsServiceError,
        generate_speech,
    )

    try:
        generate_speech(text=text, output_path=str(output_path), voice_id=config.voice or None)
    except integrations.IntegrationNotConfigured as exc:
        raise NarrationError(
            "Narration is set to ElevenLabs, but no ElevenLabs API key is saved. Add one in "
            "Settings → Narration, or switch to the free Edge TTS provider.",
            provider="elevenlabs",
        ) from exc
    except ElevenLabsServiceError as exc:
        output_path.unlink(missing_ok=True)
        raise NarrationError(str(exc), provider="elevenlabs", retryable=True) from exc
    return NarrationResult(
        path=output_path,
        provider="elevenlabs",
        voice=config.voice or DEFAULT_VOICE_ID,
        duration_seconds=0.0,
    )


def synthesize(
    text: str, output_path: Path, config: NarrationConfig | None = None
) -> NarrationResult:
    """Write MP3 narration with the selected provider and measure its duration."""
    config = config or current_config()
    script = " ".join(text.split())
    if not script:
        raise ValueError("Narration text must not be blank")
    output_path = output_path.with_suffix(".mp3")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if config.provider == "edge":
            result = _edge(script, output_path, config)
        else:
            result = _elevenlabs(script, output_path, config)
        check_cancelled()
        result.normalized = normalize_loudness(output_path)
        result.duration_seconds = audio_duration(output_path)
    except BaseException:
        output_path.unlink(missing_ok=True)
        raise
    if result.duration_seconds <= 0:
        output_path.unlink(missing_ok=True)
        raise NarrationError(
            f"{config.label} returned audio with no duration.",
            provider=config.provider,
            retryable=True,
        )
    return result


def find_narration_error(exc: BaseException | None) -> NarrationError | None:
    depth = 0
    while exc is not None and depth < 12:
        if isinstance(exc, NarrationError):
            return exc
        exc = exc.__cause__ or exc.__context__
        depth += 1
    return None
