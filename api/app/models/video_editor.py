from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, validator

from app.models.producer import ShortFormat
from app.models.video_tools import VideoProductionResult


class VideoEditorRequest(BaseModel):
    edit_brief: str = Field(
        ...,
        min_length=5,
        max_length=3000,
        description="What to change or optimize in the video",
        examples=["Make the hook punchier and use electric-themed b-roll"],
    )
    script: str = Field(
        ...,
        min_length=1,
        max_length=2500,
        description="Current or draft script to edit and render",
    )
    context: Optional[str] = Field(
        None,
        max_length=2000,
        description="Optional tone, audience, or pacing hints",
    )
    research: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional research report from POST /api/agents/research",
    )
    source_production: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional prior production report to revise",
    )
    short_format: ShortFormat = Field(
        "auto",
        description="auto, sound for narrated shorts, or silent for text-only",
    )
    cinematography: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional cinematography report from production pipeline",
    )
    visual: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional visual report from production pipeline",
    )
    voice: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional voice report from production pipeline",
    )
    music_director: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional music director report from production pipeline",
    )
    sound_design: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional sound design report from production pipeline",
    )
    score_with_music: bool = Field(
        True,
        description="When true, mux Music Director score on montage/text renders",
    )

    @validator("script")
    def script_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("script must not be blank")
        return value


class VideoEditorReport(BaseModel):
    edit_brief: str
    edited_at: str
    edit_summary: str
    visual_notes: List[str]
    final_script: str
    short_format: Literal["text_short", "sound_short"]
    rationale: str
    limitations: List[str]
    video: VideoProductionResult
    edit_data: Dict[str, Any]
