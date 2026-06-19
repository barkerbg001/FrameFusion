from typing import Literal, Optional

from pydantic import BaseModel, Field, validator


class VideoProductionResult(BaseModel):
    video_type: Literal["text_short", "sound_short", "lofi"]
    output_path: str
    output_name: str
    width: int
    height: int
    duration_seconds: float
    background_color: Optional[str] = None
    narration_audio_path: Optional[str] = None
    background_source: Optional[str] = None
    background_media_type: Optional[str] = None
    background_photographer: Optional[str] = None
    background_query: Optional[str] = None


class TextShortProductionRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)

    @validator("text")
    def text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be blank")
        return value


class SoundShortProductionRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2500)

    @validator("text")
    def text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be blank")
        return value


class LofiProductionRequest(BaseModel):
    image_path: str = Field(..., min_length=1, max_length=1000)
    audio_path: str = Field(..., min_length=1, max_length=1000)
    repeat_minutes: int = Field(60, ge=1, le=180)
