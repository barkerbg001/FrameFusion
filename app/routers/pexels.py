from typing import Union

from fastapi import APIRouter, HTTPException, Query

from app.models.pexels import (
    PexelsCombinedSearchResult,
    PexelsPhotoSearchResult,
    PexelsVideoSearchResult,
)
from app.services.pexels_client import (
    PexelsNotFoundError,
    PexelsServiceError,
    search_pexels,
    search_pexels_photos,
    search_pexels_videos,
)


router = APIRouter()


@router.get(
    "/photos/search",
    response_model=PexelsPhotoSearchResult,
)
def search_photos(
    query: str = Query(
        ...,
        min_length=2,
        max_length=200,
        description="Search terms for stock photos",
        examples=["sunset beach"],
    ),
    per_page: int = Query(15, ge=1, le=80),
    page: int = Query(1, ge=1),
    orientation: str | None = Query(
        None,
        description="Photo orientation filter",
        examples=["landscape"],
    ),
) -> PexelsPhotoSearchResult:
    try:
        return PexelsPhotoSearchResult(**search_pexels_photos(
            query,
            per_page=per_page,
            page=page,
            orientation=orientation,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PexelsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PexelsServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/videos/search",
    response_model=PexelsVideoSearchResult,
)
def search_videos(
    query: str = Query(
        ...,
        min_length=2,
        max_length=200,
        description="Search terms for stock videos",
        examples=["city timelapse"],
    ),
    per_page: int = Query(15, ge=1, le=80),
    page: int = Query(1, ge=1),
) -> PexelsVideoSearchResult:
    try:
        return PexelsVideoSearchResult(**search_pexels_videos(
            query,
            per_page=per_page,
            page=page,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PexelsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PexelsServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/search")
def search_media(
    query: str = Query(
        ...,
        min_length=2,
        max_length=200,
        description="Search terms for stock media",
        examples=["rain forest"],
    ),
    media_type: str = Query(
        "video",
        description="Return photos, videos, or both",
        examples=["video"],
    ),
    per_page: int = Query(15, ge=1, le=80),
    page: int = Query(1, ge=1),
    orientation: str | None = Query(
        None,
        description="Photo orientation filter when searching photos",
    ),
) -> Union[PexelsPhotoSearchResult, PexelsVideoSearchResult, PexelsCombinedSearchResult]:
    try:
        result = search_pexels(
            query,
            media_type=media_type,
            per_page=per_page,
            page=page,
            orientation=orientation,
        )
        if media_type == "photo":
            return PexelsPhotoSearchResult(**result)
        if media_type == "video":
            return PexelsVideoSearchResult(**result)
        return PexelsCombinedSearchResult(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PexelsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PexelsServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
