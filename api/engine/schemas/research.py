from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from engine.schemas.history import HistoryCitation


class MediaRecommendation(BaseModel):
    media_type: str
    description: str
    url: str
    download_url: Optional[str] = None
    preview_url: Optional[str] = None
    photographer: Optional[str] = None
    duration_seconds: Optional[int] = None


class ResearchFindings(BaseModel):
    """The part of a ResearchReport the model writes; the server fills in the rest."""

    summary: str
    verified_facts: List[str] = Field(default_factory=list)
    content_hooks: List[str] = Field(default_factory=list)
    visual_suggestions: List[str] = Field(default_factory=list)
    citations: List[HistoryCitation] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class ResearchReport(BaseModel):
    task: str
    researched_at: str
    summary: str
    verified_facts: List[str]
    content_hooks: List[str]
    visual_suggestions: List[str]
    recommended_media: List[MediaRecommendation]
    citations: List[HistoryCitation]
    tools_used: List[str]
    limitations: List[str]
    research_data: Dict[str, Any]
