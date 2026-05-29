from enum import StrEnum

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(StrEnum):
    LOFI = "lofi"
    SLIDESHOW = "slideshow"
    SHORTS = "shorts"
    BATCH = "batch"


class JobRecord(BaseModel):
    id: str
    job_type: JobType
    status: JobStatus
    progress: float = Field(ge=0, le=100)
    payload: dict[str, object]
    output_path: str | None = None
    output_filename: str | None = None
    media_type: str | None = None
    error: str | None = None
    workspace_path: str
    created_at: float
    updated_at: float


class JobCreateResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    id: str
    job_type: JobType
    status: JobStatus
    progress: float
    created_at: float
    updated_at: float
    output_filename: str | None = None
    error: str | None = None
