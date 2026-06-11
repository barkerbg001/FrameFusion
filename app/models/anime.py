from typing import Any, Dict, List

from pydantic import BaseModel, Field

from app.models.history import HistoryCitation


class AnimeResearchRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    question: str = Field(
        "Provide a factual, spoiler-light anime briefing.",
        min_length=1,
        max_length=1500,
    )
    max_sources: int = Field(3, ge=1, le=5)
    allow_spoilers: bool = False


class AnimeResearchReport(BaseModel):
    title: str
    researched_at: str
    summary: str
    format_and_release: List[str]
    creators_and_studios: List[str]
    premise: str
    themes: List[str]
    verified_facts: List[str]
    content_hooks: List[str]
    short_video_script: str
    spoiler_warning: str
    citations: List[HistoryCitation]
    limitations: List[str]
    source: str
    research_data: Dict[str, Any]
