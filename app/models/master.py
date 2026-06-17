from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.history import HistoryCitation
from app.models.producer import ProducerReport


ShortFormat = Literal["auto", "sound", "silent"]


class MasterResearchRequest(BaseModel):
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


class MasterMediaRecommendation(BaseModel):
    media_type: str
    description: str
    url: str
    preview_url: Optional[str] = None
    photographer: Optional[str] = None
    duration_seconds: Optional[int] = None


class MasterResearchReport(BaseModel):
    task: str
    researched_at: str
    summary: str
    verified_facts: List[str]
    content_hooks: List[str]
    short_video_script: str
    visual_suggestions: List[str]
    recommended_media: List[MasterMediaRecommendation]
    citations: List[HistoryCitation]
    tools_used: List[str]
    researchers_used: List[str] = Field(default_factory=list)
    limitations: List[str]
    research_data: Dict[str, Any]


class MasterAgentReport(MasterResearchReport):
    production: Optional[ProducerReport] = None
