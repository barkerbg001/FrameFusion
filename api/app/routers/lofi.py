import os

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse

from app.core.upload_helpers import (
    make_temp_workspace,
    persist_uploaded_audio,
    persist_uploaded_images,
    run_video_generation,
    safe_filename,
)
from app.services.video_creator import create_video_from_images_and_audio

router = APIRouter()


@router.post("/generate-video", response_class=FileResponse)
async def generate_video(
    images: list[UploadFile] = File(...),
    audio: UploadFile = File(...),
    output_name: str = Form("output.mp4"),
    repeat_minutes: int = Form(60),
):
    output_name = safe_filename(output_name, "output.mp4")
    workspace, cleanup = make_temp_workspace()

    image_paths = await persist_uploaded_images(workspace, images)
    audio_path = await persist_uploaded_audio(workspace, audio)

    output_dir = os.path.join(workspace, "output")
    os.makedirs(output_dir, exist_ok=True)

    video_path = run_video_generation(
        lambda: create_video_from_images_and_audio(
            image_paths=image_paths,
            audio_path=audio_path,
            output_path=output_dir,
            output_name=output_name,
            repeat_minutes=repeat_minutes,
        ),
        log_message="Lofi video generation failed",
    )

    return FileResponse(
        video_path,
        media_type="video/mp4",
        filename=output_name,
        background=cleanup,
    )
