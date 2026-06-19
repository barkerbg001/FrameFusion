from typing import Optional

from pydantic import BaseModel, Field, validator

class VideoBatchRequest(BaseModel):
    count: int  # How many videos to create


class TextShortRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    duration_seconds: float = Field(10, ge=1, le=60)
    background_color: Optional[str] = None
    text_color: str = "#FFFFFF"
    font_size: int = Field(96, ge=36, le=180)
    output_name: str = "text-short.mp4"

    @validator("text")
    def text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be blank")
        return value

    @validator("background_color", "text_color")
    def colors_must_be_hex(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        normalized = value.strip().upper()
        if len(normalized) != 7 or not normalized.startswith("#"):
            raise ValueError("color must use the #RRGGBB format")

        try:
            int(normalized[1:], 16)
        except ValueError as exc:
            raise ValueError("color must use the #RRGGBB format") from exc

        return normalized

    @validator("output_name")
    def output_name_must_be_safe(cls, value: str) -> str:
        if value != value.split("/")[-1] or value != value.split("\\")[-1]:
            raise ValueError("output_name must be a filename without a path")
        if not value.lower().endswith(".mp4"):
            raise ValueError("output_name must end with .mp4")
        return value


class SoundVideoRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2500)
    voice_id: Optional[str] = None
    model_id: str = "eleven_multilingual_v2"
    language_code: Optional[str] = Field(None, min_length=2, max_length=2)
    background_color: Optional[str] = None
    text_color: str = "#FFFFFF"
    font_size: int = Field(96, ge=36, le=180)
    output_name: str = "sound-video.mp4"

    @validator("text")
    def narration_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be blank")
        return value

    @validator("voice_id", "model_id")
    def identifiers_must_not_be_blank(
        cls,
        value: Optional[str],
    ) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("identifier must not be blank")
        return value.strip() if value is not None else value

    @validator("background_color", "text_color")
    def sound_video_colors_must_be_hex(
        cls,
        value: Optional[str],
    ) -> Optional[str]:
        return TextShortRequest.colors_must_be_hex(value)

    @validator("output_name")
    def sound_video_output_name_must_be_safe(cls, value: str) -> str:
        return TextShortRequest.output_name_must_be_safe(value)
