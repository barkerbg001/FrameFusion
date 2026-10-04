from typing import Any, Dict, List

from pydantic import BaseModel, Field


class HistoryResearchRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=300)
    question: str = Field(
        "Provide a concise, factual historical briefing.",
        min_length=1,
        max_length=1500,
    )
    max_sources: int = Field(3, ge=1, le=5)


class HistoryCitation(BaseModel):
    source_number: int
    title: str
    url: str


class HistoryResearchReport(BaseModel):
    topic: str
    researched_at: str
    summary: str
    timeline: List[str]
    key_people: List[str]
    causes: List[str]
    consequences: List[str]
    verified_facts: List[str]
    uncertainties: List[str]
    content_hooks: List[str]
    short_video_script: str
    citations: List[HistoryCitation]
    limitations: List[str]
    source: str
    research_data: Dict[str, Any]
