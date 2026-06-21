from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, validator


class MusicComposerRequest(BaseModel):
    brief: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="What the music should feel like, e.g. chill lofi for a study montage",
    )
    context: Optional[str] = Field(
        None,
        max_length=2000,
        description="Optional video or scene context",
    )
    duration_seconds: int = Field(
        30,
        ge=3,
        le=600,
        description="Target track length in seconds",
    )
    mood: Optional[str] = Field(
        None,
        max_length=120,
        description="Optional mood hint such as upbeat, dark, or calm",
    )
    genre: Optional[str] = Field(
        None,
        max_length=120,
        description="Optional genre hint such as electronic, orchestral, or lofi",
    )
    instrumental: bool = True

    @validator("brief")
    def brief_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("brief must not be blank")
        return value


class MusicProductionResult(BaseModel):
    audio_type: Literal["music"] = "music"
    provider: Literal["elevenlabs", "procedural"]
    output_path: str
    output_name: str
    prompt: str
    duration_seconds: float
    force_instrumental: bool = True


class MusicComposerReport(BaseModel):
    brief: str
    composed_at: str
    genre: str
    mood: str
    rationale: str
    limitations: List[str]
    music: MusicProductionResult
    composition_data: Dict[str, Any] = Field(default_factory=dict)
