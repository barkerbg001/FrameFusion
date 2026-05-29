from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile

from app.core.upload_helpers import safe_filename
from app.jobs.models import JobCreateResponse
from app.jobs.submit import submit_slideshow_job

router = APIRouter()


@router.post("/generate", status_code=202, response_model=JobCreateResponse)
async def generate_slideshow(
    background_tasks: BackgroundTasks,
    images: list[UploadFile] = File(...),
    audio: UploadFile = File(...),
    output_name: str = Form("slideshow.mp4"),
    fps: int = Form(30),
    orientation: str = Form("landscape"),
):
    output_name = safe_filename(output_name, "slideshow.mp4")
    return await submit_slideshow_job(
        images=images,
        audio=audio,
        output_name=output_name,
        fps=fps,
        orientation=orientation,
        background_tasks=background_tasks,
    )
