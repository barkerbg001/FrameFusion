from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class PexelsPhotoSrc(BaseModel):
    original: Optional[str] = None
    large: Optional[str] = None
    medium: Optional[str] = None
    small: Optional[str] = None
    portrait: Optional[str] = None


class PexelsPhoto(BaseModel):
    id: int
    url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    avg_color: Optional[str] = None
    alt: Optional[str] = None
    photographer: Optional[str] = None
    photographer_url: Optional[str] = None
    src: PexelsPhotoSrc


class PexelsPhotoSearchResult(BaseModel):
    query: str
    media_type: Literal["photo"] = "photo"
    page: int
    per_page: int
    total_results: int
    next_page: Optional[str] = None
    source: str
    attribution: str
    photos: List[PexelsPhoto]


class PexelsVideo(BaseModel):
    id: int
    url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration_seconds: Optional[int] = None
    preview_image: Optional[str] = None
    photographer: Optional[str] = None
    photographer_url: Optional[str] = None
    video_url: Optional[str] = None
    video_quality: Optional[str] = None
    video_width: Optional[int] = None
    video_height: Optional[int] = None


class PexelsVideoSearchResult(BaseModel):
    query: str
    media_type: Literal["video"] = "video"
    page: int
    per_page: int
    total_results: int
    next_page: Optional[str] = None
    source: str
    attribution: str
    videos: List[PexelsVideo]


class PexelsCombinedSearchResult(BaseModel):
    query: str
    media_type: Literal["both"] = "both"
    page: int
    per_page: int
    source: str
    attribution: str
    photos: List[PexelsPhoto]
    videos: List[PexelsVideo]
    photo_total_results: int
    video_total_results: int


class PexelsSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=200)
    media_type: Literal["photo", "video", "both"] = "video"
    per_page: int = Field(15, ge=1, le=80)
    page: int = Field(1, ge=1)
    orientation: Optional[Literal["landscape", "portrait", "square"]] = None
