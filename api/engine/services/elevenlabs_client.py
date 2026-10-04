"""ElevenLabs speech and music generation for renders.

Docs: https://elevenlabs.io/docs/api-reference/introduction
The API key, voice, speech model, voice settings and music model come from Settings
(``engine.integrations``); explicit arguments override the saved values.
Both endpoints consume ElevenLabs credits.
"""

import json
import os
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from engine import integrations

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
DEFAULT_MODEL_ID = "eleven_multilingual_v2"
DEFAULT_MUSIC_MODEL = "music_v2"


class ElevenLabsServiceError(Exception):
    pass


def _api_key() -> str:
    key = integrations.get_key("elevenlabs")
    if not key:
        raise integrations.IntegrationNotConfigured("elevenlabs")
    return key


def is_configured() -> bool:
    return integrations.is_configured("elevenlabs")


def saved_settings() -> dict[str, Any]:
    return integrations.get_settings("elevenlabs")


def _voice_settings(saved: dict[str, Any]) -> dict[str, Any]:
    values = saved.get("voice_settings") or {}
    return {key: value for key, value in values.items() if value is not None}


def _error_message(exc: HTTPError) -> str:
    message = f"ElevenLabs returned HTTP {exc.code}"
    if exc.code == 401:
        message = "ElevenLabs rejected the API key. Check it in Settings → Narration."
    elif exc.code == 429:
        message = "ElevenLabs rate limit or concurrency limit reached. Try again shortly."
    try:
        error_body = json.loads(exc.read().decode("utf-8"))
        detail = error_body.get("detail")
        if isinstance(detail, dict):
            message = detail.get("message") or message
        elif isinstance(detail, str):
            message = detail
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        pass
    return message[:400]


def _post_audio(url: str, payload: dict[str, Any], output_path: str, timeout: int) -> None:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": _api_key(),
            "User-Agent": "FrameFusion/1.0",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        with open(output_path, "wb") as output_file:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                output_file.write(chunk)


def generate_speech(
    text: str,
    output_path: str,
    voice_id: Optional[str] = None,
    model_id: Optional[str] = None,
    language_code: Optional[str] = None,
) -> str:
    """Generate an MP3 narration with ElevenLabs and save it to output_path."""
    saved = saved_settings()
    selected_voice = voice_id or saved.get("voice_id") or DEFAULT_VOICE_ID
    selected_model = model_id or saved.get("model_id") or DEFAULT_MODEL_ID
    query = urlencode({"output_format": "mp3_44100_128"})
    url = f"{ELEVENLABS_BASE_URL}/text-to-speech/{selected_voice}?{query}"
    payload: dict[str, Any] = {"text": text, "model_id": selected_model}
    settings = _voice_settings(saved)
    if settings:
        payload["voice_settings"] = settings
    if language_code:
        payload["language_code"] = language_code.lower()

    try:
        _post_audio(url, payload, output_path, timeout=60)
    except HTTPError as exc:
        raise ElevenLabsServiceError(_error_message(exc)) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ElevenLabsServiceError("Unable to generate speech with ElevenLabs") from exc

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise ElevenLabsServiceError("ElevenLabs returned empty audio")
    return output_path


def generate_music(
    prompt: str,
    output_path: str,
    duration_seconds: int = 30,
    model_id: Optional[str] = None,
    force_instrumental: bool = True,
) -> str:
    """Generate an MP3 track with ElevenLabs Music and save it to output_path."""
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise ElevenLabsServiceError("Music prompt must not be blank")

    clamped_seconds = max(3, min(duration_seconds, 600))
    selected_model = model_id or saved_settings().get("music_model") or DEFAULT_MUSIC_MODEL
    payload: dict[str, Any] = {
        "prompt": normalized_prompt,
        "music_length_ms": clamped_seconds * 1000,
        "model_id": selected_model,
    }
    if force_instrumental:
        payload["force_instrumental"] = True

    try:
        _post_audio(f"{ELEVENLABS_BASE_URL}/music", payload, output_path, timeout=180)
    except HTTPError as exc:
        raise ElevenLabsServiceError(_error_message(exc)) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ElevenLabsServiceError("Unable to generate music with ElevenLabs") from exc

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise ElevenLabsServiceError("ElevenLabs returned empty music")
    return output_path
