from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, validator

from app.models.video_tools import VideoProductionResult


ShortFormat = Literal["auto", "sound", "silent"]


class ProducerRequest(BaseModel):
    script: str = Field(..., min_length=1, max_length=2500)
    context: Optional[str] = Field(
        None,
        max_length=2000,
        description="Optional tone or pacing hints",
    )
    short_format: ShortFormat = "auto"

    @validator("script")
    def script_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("script must not be blank")
        return value


class ProducerReport(BaseModel):
    script: str
    produced_at: str
    short_format: Literal["text_short", "sound_short"]
    rationale: str
    limitations: List[str]
    video: VideoProductionResult
    production_data: Dict[str, Any]
