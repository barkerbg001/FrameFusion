from fastapi import APIRouter, HTTPException

from app.agents.base import run_tool
from app.models.video_tools import (
    LofiProductionRequest,
    SoundShortProductionRequest,
    TextShortProductionRequest,
    VideoProductionResult,
)
from app.services.output_filename import resolve_output_name
from app.services.video_producer import (
    VideoProducerError,
    produce_sound_short_simple,
    produce_text_short_simple,
)


router = APIRouter()


@router.post("/text-short", response_model=VideoProductionResult)
def create_text_short_video(
    request: TextShortProductionRequest,
) -> VideoProductionResult:
    try:
        return VideoProductionResult(
            **produce_text_short_simple(
                text=request.text,
                output_name=resolve_output_name(
                    request.text,
                    default_stem="text-short",
                ),
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VideoProducerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/sound-short", response_model=VideoProductionResult)
def create_sound_short_video(
    request: SoundShortProductionRequest,
) -> VideoProductionResult:
    try:
        return VideoProductionResult(
            **produce_sound_short_simple(
                text=request.text,
                output_name=resolve_output_name(
                    request.text,
                    default_stem="sound-short",
                ),
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VideoProducerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/lofi", response_model=VideoProductionResult)
def create_lofi_video(request: LofiProductionRequest) -> VideoProductionResult:
    try:
        result = run_tool(
            "lofi",
            {
                "image_path": request.image_path,
                "audio_path": request.audio_path,
                "repeat_minutes": request.repeat_minutes,
            },
        )
        if "error" in result:
            raise HTTPException(status_code=502, detail=result["error"])
        return VideoProductionResult(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
