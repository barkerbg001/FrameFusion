from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from typing import List
from app.services.video_creator import create_video_from_images_and_audio
import tempfile
import shutil
import os

router = APIRouter()

@router.post("/generate-video", response_class=FileResponse)
async def generate_video(
    images: List[UploadFile] = File(...),
    audio: UploadFile = File(...),
    output_name: str = Form("output.mp4"),
    repeat_minutes: int = Form(60),
):
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # Save audio
            audio_path = os.path.join(temp_dir, audio.filename)
            with open(audio_path, "wb") as f:
                shutil.copyfileobj(audio.file, f)

            # Save images
            image_paths = []
            for img in images:
                img_path = os.path.join(temp_dir, img.filename)
                with open(img_path, "wb") as f:
                    shutil.copyfileobj(img.file, f)
                image_paths.append(img_path)

            # Generate video
            output_dir = os.path.join(temp_dir, "output")
            os.makedirs(output_dir, exist_ok=True)

            video_path = create_video_from_images_and_audio(
                image_paths=image_paths,
                audio_path=audio_path,
                output_path=output_dir,
                output_name=output_name,
                repeat_minutes=repeat_minutes
            )

            # Return the generated video as a file
            return FileResponse(video_path, media_type="video/mp4", filename=output_name)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
