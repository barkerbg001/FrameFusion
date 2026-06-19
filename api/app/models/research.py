from typing import Any, Dict, List

from pydantic import BaseModel, Field

from app.models.history import HistoryCitation
from app.models.director import DirectorMediaRecommendation


class ResearchReport(BaseModel):
    task: str
    researched_at: str
    summary: str
    verified_facts: List[str]
    content_hooks: List[str]
    visual_suggestions: List[str]
    recommended_media: List[DirectorMediaRecommendation]
    citations: List[HistoryCitation]
    tools_used: List[str]
    limitations: List[str]
    research_data: Dict[str, Any]
