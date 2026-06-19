from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.master import ShortFormat


class IdeaRequest(BaseModel):
    topic: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Niche, theme, or subject to brainstorm around",
        examples=["Pokemon facts", "Johannesburg weather shorts"],
    )
    context: Optional[str] = Field(
        None,
        max_length=2000,
        description="Optional constraints such as tone, platform, or angle",
    )
    audience: Optional[str] = Field(
        None,
        max_length=500,
        description="Who the content is for, e.g. commuters or anime fans",
    )
    idea_count: int = Field(
        5,
        ge=1,
        le=10,
        description="How many distinct short-form ideas to generate",
    )


class VideoIdea(BaseModel):
    title: str
    hook: str
    concept: str
    research_task: str = Field(
        description="Task text ready to pass to the researcher or master agent",
    )
    suggested_format: ShortFormat = "auto"
    visual_angle: str
    why_it_works: str


class IdeaReport(BaseModel):
    topic: str
    generated_at: str
    summary: str
    ideas: List[VideoIdea]
    tools_used: List[str] = Field(default_factory=list)
    limitations: List[str]
