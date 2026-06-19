from typing import Optional

from pydantic import BaseModel, Field

from app.models.research import ResearchReport


class ResearcherRequest(BaseModel):
    task: str = Field(
        ...,
        min_length=5,
        max_length=3000,
        description="What to research for short-form content",
        examples=[
            "Brief me on Pikachu for a Pokemon short",
            "Weather outlook for Cape Town this week",
        ],
    )
    context: Optional[str] = Field(
        None,
        max_length=2000,
        description="Optional hints such as location, subject, tone, or spoiler policy",
    )


ResearcherReport = ResearchReport
