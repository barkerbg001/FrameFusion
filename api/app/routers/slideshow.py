from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile

from app.core.config import RATE_LIMIT_GENERATE
from app.core.rate_limit import GENERATE_SCOPE, limiter
from app.core.upload_helpers import safe_filename
from app.jobs.models import JobCreateResponse
from app.jobs.submit import submit_slideshow_job

router = APIRouter()


@router.post("/generate", status_code=202, response_model=JobCreateResponse)
@limiter.shared_limit(RATE_LIMIT_GENERATE, scope=GENERATE_SCOPE)
async def generate_slideshow(
    request: Request,
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
