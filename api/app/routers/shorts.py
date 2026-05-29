from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile

from app.core.upload_helpers import safe_filename
from app.jobs.models import JobCreateResponse
from app.jobs.submit import submit_shorts_job

router = APIRouter()


@router.post("/generate", status_code=202, response_model=JobCreateResponse)
async def generate_shorts(
    background_tasks: BackgroundTasks,
    images: list[UploadFile] = File(...),
    audio: UploadFile | None = File(None),
    output_name: str = Form("shorts.mp4"),
    seconds_per_image: float = Form(1.0),
    orientation: str = Form("portrait"),
    shuffle: bool = Form(True),
    max_duration_seconds: float | None = Form(None),
    fps: int = Form(30),
):
    output_name = safe_filename(output_name, "shorts.mp4")
    return await submit_shorts_job(
        images=images,
        audio=audio,
        output_name=output_name,
        seconds_per_image=seconds_per_image,
        orientation=orientation,
        shuffle=shuffle,
        max_duration_seconds=max_duration_seconds,
        fps=fps,
        background_tasks=background_tasks,
    )
