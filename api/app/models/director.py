from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.research import ResearchReport
from app.models.video_editor import VideoEditorReport


ShortFormat = Literal["auto", "sound", "silent"]


class DirectorRequest(BaseModel):
    task: str = Field(
        ...,
        min_length=5,
        max_length=3000,
        description="What to research and turn into a short-form video",
        examples=[
            "Create a weather briefing short about Johannesburg this week",
        ],
    )
    context: Optional[str] = Field(
        None,
        max_length=2000,
        description="Optional hints such as location, subject, or tone",
    )
    produce_short: bool = Field(
        True,
        description="When true, render a short video from the researched script",
    )
    short_format: ShortFormat = Field(
        "auto",
        description="auto, sound for narrated shorts, or silent for text-only",
    )


class DirectorResearchReport(ResearchReport):
    short_video_script: str = ""
    researchers_used: List[str] = Field(default_factory=list)


class DirectorReport(DirectorResearchReport):
    screenwriter: Optional[Dict[str, Any]] = None
    production: Optional[VideoEditorReport] = None
