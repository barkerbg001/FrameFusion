from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile

from app.core.upload_helpers import safe_filename
from app.jobs.models import JobCreateResponse
from app.jobs.submit import submit_lofi_job

router = APIRouter()


@router.post("/generate-video", status_code=202, response_model=JobCreateResponse)
async def generate_video(
    background_tasks: BackgroundTasks,
    images: list[UploadFile] = File(...),
    audio: UploadFile = File(...),
    output_name: str = Form("output.mp4"),
    repeat_minutes: int = Form(60),
):
    output_name = safe_filename(output_name, "output.mp4")
    return await submit_lofi_job(
        images=images,
        audio=audio,
        output_name=output_name,
        repeat_minutes=repeat_minutes,
        background_tasks=background_tasks,
    )
