from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ScreenwriterRequest(BaseModel):
    task: str = Field(
        ...,
        min_length=5,
        max_length=3000,
        description="Topic or angle for the short-form script",
        examples=["Why Pikachu outsells Charizard in merch"],
    )
    context: Optional[str] = Field(
        None,
        max_length=2000,
        description="Optional tone, audience, or format hints",
    )
    research: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional research report from POST /api/agents/research",
    )
    target_words: int = Field(
        90,
        ge=45,
        le=180,
        description="Target script length in words",
    )
    style: str = Field(
        "short-form factual",
        max_length=100,
        description="Writing style such as punchy, educational, or conversational",
    )


class ScreenwriterReport(BaseModel):
    task: str
    written_at: str
    short_video_script: str
    word_count: int
    tone: str
    hooks_used: List[str]
    limitations: List[str]
