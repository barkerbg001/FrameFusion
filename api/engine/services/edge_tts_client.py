"""Free narration through Microsoft Edge's online text-to-speech service.

Uses the ``edge-tts`` package (https://github.com/rany2/edge-tts). This is not local or
offline synthesis: the narration text is sent over the internet to Microsoft's speech
service, which streams back MP3 audio (24 kHz mono) and word/sentence timing events.
No API key is involved. The service is unofficial and may change, rate-limit or
become unavailable without notice, so every failure is reported to the user instead
of switching to a paid provider.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.runtime import check_cancelled

DEFAULT_VOICE = "en-US-EmmaMultilingualNeural"
CONNECT_TIMEOUT_SECONDS = 10
RECEIVE_TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 3
VOICE_CACHE_SECONDS = 12 * 60 * 60
CANCEL_CHECK_SECONDS = 0.5
VOICE_PATTERN = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*-[A-Za-z0-9]{1,40}Neural$")

RATE_RANGE = (-50, 100)
PITCH_RANGE = (-50, 50)
VOLUME_RANGE = (-50, 50)

# The speech service is a shared, unofficial endpoint: keep simultaneous syntheses low.
_concurrency = threading.BoundedSemaphore(2)
_voice_lock = threading.Lock()
_voice_cache: tuple[float, list[dict[str, Any]]] | None = None


class EdgeTTSError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass
class EdgeSpeech:
    path: Path
    voice: str
    words: list[tuple[float, float, str]] = field(default_factory=list)
    sentences: list[tuple[float, float, str]] = field(default_factory=list)


def _signed(value: int, unit: str) -> str:
    return f"{'+' if value >= 0 else '-'}{abs(int(value))}{unit}"


def _clamp(value: int, bounds: tuple[int, int]) -> int:
    return max(bounds[0], min(bounds[1], int(value)))


def prosody(rate: int = 0, pitch: int = 0, volume: int = 0) -> dict[str, str]:
    """Format controls the way edge-tts validates them: +N% / -N% and +NHz / -NHz."""
    return {
        "rate": _signed(_clamp(rate, RATE_RANGE), "%"),
        "pitch": _signed(_clamp(pitch, PITCH_RANGE), "Hz"),
        "volume": _signed(_clamp(volume, VOLUME_RANGE), "%"),
    }


def _voice_payload(voice: dict[str, Any]) -> dict[str, Any]:
    tag = voice.get("VoiceTag") or {}
    short_name = str(voice.get("ShortName") or "")
    friendly = str(voice.get("FriendlyName") or short_name)
    display = friendly.replace("Microsoft ", "").split(" Online")[0].strip() or short_name
    locale = str(voice.get("Locale") or "")
    language = friendly.split(" - ", 1)[1].strip() if " - " in friendly else ""
    return {
        "id": short_name,
        "name": display,
        "locale": locale,
        "locale_name": language or locale,
        "gender": voice.get("Gender") or "",
        "status": voice.get("Status") or "",
        "personalities": list(tag.get("VoicePersonalities") or []),
        "categories": list(tag.get("ContentCategories") or []),
    }


def _network_error(exc: BaseException) -> bool:
    import aiohttp
    import edge_tts.exceptions as edge_exc

    return isinstance(
        exc,
        (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            TimeoutError,
            ConnectionError,
            edge_exc.WebSocketError,
            edge_exc.SkewAdjustmentError,
        ),
    )


def list_voices(*, refresh: bool = False) -> list[dict[str, Any]]:
    """Voices offered by the service, cached in memory for 12 hours."""
    global _voice_cache
    with _voice_lock:
        if (
            not refresh
            and _voice_cache
            and time.monotonic() - _voice_cache[0] < VOICE_CACHE_SECONDS
        ):
            return _voice_cache[1]
    import edge_tts

    try:
        raw = asyncio.run(edge_tts.list_voices())
    except Exception as exc:
        if _network_error(exc):
            raise EdgeTTSError(
                "Couldn't reach the Edge TTS service to load voices. Check your internet "
                "connection and try again.",
                retryable=True,
            ) from exc
        raise EdgeTTSError(
            f"The Edge TTS service returned an unexpected voice list: {exc}"
        ) from exc
    voices = sorted(
        (_voice_payload(v) for v in raw if v.get("ShortName")),
        key=lambda v: (v["locale_name"], v["name"]),
    )
    with _voice_lock:
        _voice_cache = (time.monotonic(), voices)
    return voices


def cached_voice(voice_id: str) -> dict[str, Any] | None:
    with _voice_lock:
        voices = _voice_cache[1] if _voice_cache else []
    return next((v for v in voices if v["id"] == voice_id), None)


def _known_voice_check(voice: str) -> None:
    if not VOICE_PATTERN.match(voice):
        raise EdgeTTSError(f"“{voice}” is not a valid Edge TTS voice name.")
    with _voice_lock:
        voices = _voice_cache[1] if _voice_cache else None
    if voices is not None and not any(v["id"] == voice for v in voices):
        raise EdgeTTSError(
            f"The Edge TTS voice “{voice}” is no longer offered. Choose another voice in "
            "Settings → Narration."
        )


async def _stream_to_file(
    text: str, voice: str, controls: dict[str, str], output_path: Path
) -> EdgeSpeech:
    import edge_tts

    communicate = edge_tts.Communicate(
        text,
        voice,
        boundary="WordBoundary",
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        receive_timeout=RECEIVE_TIMEOUT_SECONDS,
        **controls,
    )
    speech = EdgeSpeech(path=output_path, voice=voice)
    last_check: float | None = None
    with output_path.open("wb") as handle:
        async for chunk in communicate.stream():
            now = time.monotonic()
            if last_check is None or now - last_check >= CANCEL_CHECK_SECONDS:
                last_check = now
                # The job's cancel check queries the database, which Django forbids on a
                # thread that is running an event loop.
                await asyncio.to_thread(check_cancelled)
            if chunk["type"] == "audio":
                handle.write(chunk.get("data", b""))
            else:
                # Offsets and durations are reported in 100-nanosecond ticks.
                start = float(chunk.get("offset", 0)) / 1e7
                end = start + float(chunk.get("duration", 0)) / 1e7
                entry = (round(start, 3), round(end, 3), str(chunk.get("text", "")))
                (speech.words if chunk["type"] == "WordBoundary" else speech.sentences).append(
                    entry
                )
    return speech


def synthesize(
    text: str,
    output_path: Path,
    *,
    voice: str = DEFAULT_VOICE,
    rate: int = 0,
    pitch: int = 0,
    volume: int = 0,
) -> EdgeSpeech:
    """Write MP3 narration to ``output_path``; removes partial output on any failure."""
    script = text.strip()
    if not script:
        raise EdgeTTSError("Narration text is empty.")
    voice = (voice or DEFAULT_VOICE).strip()
    _known_voice_check(voice)
    controls = prosody(rate, pitch, volume)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    import edge_tts.exceptions as edge_exc

    last_error: BaseException | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        check_cancelled()
        try:
            with _concurrency:
                speech = asyncio.run(_stream_to_file(script, voice, controls, output_path))
            if not output_path.is_file() or output_path.stat().st_size == 0:
                raise edge_exc.NoAudioReceived("empty audio")
            return speech
        except edge_exc.NoAudioReceived as exc:
            output_path.unlink(missing_ok=True)
            # An unknown voice or rejected text also ends with no audio, so retry once only.
            last_error = exc
            if attempt >= 2:
                raise EdgeTTSError(
                    f"Edge TTS returned no audio for the voice “{voice}”. The voice may be "
                    "unavailable; choose another voice or try again later.",
                    retryable=True,
                ) from exc
        except ValueError as exc:
            output_path.unlink(missing_ok=True)
            raise EdgeTTSError(f"Edge TTS rejected the request: {exc}") from exc
        except BaseException as exc:
            output_path.unlink(missing_ok=True)
            if not _network_error(exc):
                if isinstance(exc, edge_exc.EdgeTTSException):
                    raise EdgeTTSError(
                        f"The Edge TTS service sent an unexpected response: {exc}", retryable=True
                    ) from exc
                raise
            last_error = exc
        if attempt < MAX_ATTEMPTS:
            time.sleep(1.5 * attempt)
    raise EdgeTTSError(
        "Couldn't reach the Edge TTS service after several attempts. Check your internet "
        "connection, then retry the narration.",
        retryable=True,
    ) from last_error
