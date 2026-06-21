import json
import os
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv


ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"


class ElevenLabsServiceError(Exception):
    pass


def generate_speech(
    text: str,
    output_path: str,
    voice_id: Optional[str] = None,
    model_id: str = "eleven_multilingual_v2",
    language_code: Optional[str] = None,
) -> str:
    """Generate an MP3 narration with ElevenLabs and save it to output_path."""
    load_dotenv()
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise ElevenLabsServiceError(
            "ELEVENLABS_API_KEY is not configured"
        )

    selected_voice = (
        voice_id
        or os.getenv("ELEVENLABS_VOICE_ID")
        or DEFAULT_VOICE_ID
    )
    query = urlencode({"output_format": "mp3_44100_128"})
    url = (
        f"{ELEVENLABS_BASE_URL}/text-to-speech/"
        f"{selected_voice}?{query}"
    )
    payload = {
        "text": text,
        "model_id": model_id,
    }
    if language_code:
        payload["language_code"] = language_code.lower()

    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key,
            "User-Agent": "FrameFusion/1.0",
        },
    )

    try:
        with urlopen(request, timeout=60) as response:
            with open(output_path, "wb") as output_file:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    output_file.write(chunk)
    except HTTPError as exc:
        message = f"ElevenLabs returned HTTP {exc.code}"
        try:
            error_body = json.loads(exc.read().decode("utf-8"))
            detail = error_body.get("detail")
            if isinstance(detail, dict):
                message = detail.get("message") or message
            elif isinstance(detail, str):
                message = detail
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        raise ElevenLabsServiceError(message) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ElevenLabsServiceError(
            "Unable to generate speech with ElevenLabs"
        ) from exc

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise ElevenLabsServiceError("ElevenLabs returned empty audio")
    return output_path


def generate_music(
    prompt: str,
    output_path: str,
    duration_seconds: int = 30,
    model_id: str = "music_v2",
    force_instrumental: bool = True,
) -> str:
    """Generate an MP3 track with ElevenLabs Music and save it to output_path."""
    load_dotenv()
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise ElevenLabsServiceError(
            "ELEVENLABS_API_KEY is not configured"
        )

    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise ElevenLabsServiceError("Music prompt must not be blank")

    clamped_seconds = max(3, min(duration_seconds, 600))
    music_length_ms = clamped_seconds * 1000
    selected_model = os.getenv("ELEVENLABS_MUSIC_MODEL", model_id)

    payload: dict[str, object] = {
        "prompt": normalized_prompt,
        "music_length_ms": music_length_ms,
        "model_id": selected_model,
    }
    if force_instrumental:
        payload["force_instrumental"] = True

    request = Request(
        f"{ELEVENLABS_BASE_URL}/music",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key,
            "User-Agent": "FrameFusion/1.0",
        },
    )

    try:
        with urlopen(request, timeout=180) as response:
            with open(output_path, "wb") as output_file:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    output_file.write(chunk)
    except HTTPError as exc:
        message = f"ElevenLabs returned HTTP {exc.code}"
        try:
            error_body = json.loads(exc.read().decode("utf-8"))
            detail = error_body.get("detail")
            if isinstance(detail, dict):
                message = detail.get("message") or message
            elif isinstance(detail, str):
                message = detail
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        raise ElevenLabsServiceError(message) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ElevenLabsServiceError(
            "Unable to generate music with ElevenLabs"
        ) from exc

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise ElevenLabsServiceError("ElevenLabs returned empty music")
    return output_path
