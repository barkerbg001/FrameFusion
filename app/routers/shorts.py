import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask, BackgroundTasks

from app.models.video import SoundVideoRequest, TextShortRequest
from app.services.elevenlabs_client import (
    ElevenLabsServiceError,
    generate_speech,
)
from app.services.text_video_creator import create_sound_short, create_text_short


router = APIRouter()
SUPPORTED_AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".wav",
}


def _remove_file(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _validate_color(value: Optional[str], field_name: str) -> Optional[str]:
    if value is None:
        return None

    normalized = value.strip().upper()
    if len(normalized) != 7 or not normalized.startswith("#"):
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must use the #RRGGBB format",
        )
    try:
        int(normalized[1:], 16)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must use the #RRGGBB format",
        ) from exc
    return normalized


def _validate_output_name(output_name: str) -> str:
    if (
        output_name != output_name.split("/")[-1]
        or output_name != output_name.split("\\")[-1]
        or not output_name.lower().endswith(".mp4")
    ):
        raise HTTPException(
            status_code=400,
            detail="output_name must be an .mp4 filename without a path",
        )
    return output_name


@router.post("/generate-text-video", response_class=FileResponse)
def generate_text_video(request: TextShortRequest) -> FileResponse:
    output_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    output_path = output_file.name
    output_file.close()

    try:
        create_text_short(
            text=request.text,
            output_path=output_path,
            duration_seconds=request.duration_seconds,
            background_color=request.background_color,
            text_color=request.text_color,
            font_size=request.font_size,
        )
    except Exception as exc:
        _remove_file(output_path)
        raise HTTPException(
            status_code=500,
            detail=f"Unable to generate text video: {exc}",
        ) from exc

    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename=request.output_name,
        background=BackgroundTask(_remove_file, output_path),
    )


@router.post("/generate-audio-video", response_class=FileResponse)
def generate_audio_video(
    audio: UploadFile = File(...),
    text: str = Form(..., min_length=1, max_length=1000),
    background_color: Optional[str] = Form(None),
    text_color: str = Form("#FFFFFF"),
    font_size: int = Form(96, ge=36, le=180),
    output_name: str = Form("sound-short.mp4"),
) -> FileResponse:
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text must not be blank")

    audio_extension = Path(audio.filename or "").suffix.lower()
    if audio_extension not in SUPPORTED_AUDIO_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format. Use one of: {supported}",
        )

    background_color = _validate_color(
        background_color,
        "background_color",
    )
    text_color = _validate_color(text_color, "text_color") or "#FFFFFF"
    output_name = _validate_output_name(output_name)

    audio_file = tempfile.NamedTemporaryFile(
        suffix=audio_extension,
        delete=False,
    )
    output_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    audio_path = audio_file.name
    output_path = output_file.name

    try:
        with audio_file:
            shutil.copyfileobj(audio.file, audio_file)
        output_file.close()

        create_sound_short(
            text=text,
            audio_path=audio_path,
            output_path=output_path,
            background_color=background_color,
            text_color=text_color,
            font_size=font_size,
        )
    except ValueError as exc:
        _remove_file(audio_path)
        _remove_file(output_path)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _remove_file(audio_path)
        _remove_file(output_path)
        raise HTTPException(
            status_code=500,
            detail=f"Unable to generate sound video: {exc}",
        ) from exc
    finally:
        audio.file.close()

    cleanup = BackgroundTasks()
    cleanup.add_task(_remove_file, audio_path)
    cleanup.add_task(_remove_file, output_path)
    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename=output_name,
        background=cleanup,
    )


@router.post("/generate-sound-video", response_class=FileResponse)
def generate_sound_video(request: SoundVideoRequest) -> FileResponse:
    audio_file = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    output_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    audio_path = audio_file.name
    output_path = output_file.name
    audio_file.close()
    output_file.close()

    try:
        generate_speech(
            text=request.text,
            output_path=audio_path,
            voice_id=request.voice_id,
            model_id=request.model_id,
            language_code=request.language_code,
        )
        create_sound_short(
            text=request.text,
            audio_path=audio_path,
            output_path=output_path,
            background_color=request.background_color,
            text_color=request.text_color,
            font_size=request.font_size,
        )
    except ElevenLabsServiceError as exc:
        _remove_file(audio_path)
        _remove_file(output_path)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        _remove_file(audio_path)
        _remove_file(output_path)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _remove_file(audio_path)
        _remove_file(output_path)
        raise HTTPException(
            status_code=500,
            detail=f"Unable to generate sound video: {exc}",
        ) from exc

    cleanup = BackgroundTasks()
    cleanup.add_task(_remove_file, audio_path)
    cleanup.add_task(_remove_file, output_path)
    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename=request.output_name,
        background=cleanup,
    )
