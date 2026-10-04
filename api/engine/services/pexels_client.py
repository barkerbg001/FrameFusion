"""Pexels photo and video search.

Docs: https://www.pexels.com/api/documentation/
Photos: GET https://api.pexels.com/v1/search   Videos: GET https://api.pexels.com/videos/search
Both accept ``orientation`` (landscape|portrait|square) and ``size`` (large|medium|small).
The key and default orientation/size come from Settings (``engine.integrations``).

Pexels asks apps to credit photographers ("Photo by X on Pexels") and link back to
Pexels; every normalised item keeps ``photographer``, ``photographer_url`` and the
Pexels page ``url`` so callers can show attribution.
"""

import json
from typing import Any, Dict, List, Literal, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from engine import integrations

PEXELS_PHOTOS_BASE = "https://api.pexels.com/v1"
PEXELS_VIDEOS_BASE = "https://api.pexels.com/videos"
MediaType = Literal["photo", "video", "both"]
Orientation = Literal["landscape", "portrait", "square"]
Size = Literal["large", "medium", "small"]
ORIENTATIONS = ("landscape", "portrait", "square")
SIZES = ("large", "medium", "small")
USE_DEFAULT: Any = object()


class PexelsNotFoundError(Exception):
    pass


class PexelsServiceError(Exception):
    pass


def _get_api_key() -> str:
    key = integrations.get_key("pexels")
    if not key:
        raise integrations.IntegrationNotConfigured("pexels")
    return key


def _defaults() -> Dict[str, Any]:
    return integrations.get_settings("pexels")


def _resolve(value: Any, name: str, allowed: tuple[str, ...]) -> Optional[str]:
    if value is USE_DEFAULT:
        value = _defaults().get(name) or None
    if value is not None and value not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(allowed)}")
    return value


def _request_json(base: str, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    query = urlencode({key: value for key, value in params.items() if value is not None})
    url = f"{base}{path}?{query}" if query else f"{base}{path}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": _get_api_key(),
            "User-Agent": "FrameFusion/1.0 (Pexels media tool)",
        },
    )

    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise PexelsServiceError(
                "Pexels rejected the API key. Check it in Settings → Stock media."
            ) from exc
        if exc.code == 429:
            raise PexelsServiceError(
                "Pexels rate limit reached (200 requests per hour, 20,000 per month). "
                "Try again later."
            ) from exc
        raise PexelsServiceError(f"Pexels returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise PexelsServiceError("Unable to retrieve Pexels media") from exc


def _normalize_query(query: str) -> str:
    normalized = " ".join(query.strip().split())
    if len(normalized) < 2:
        raise ValueError("query must contain at least two characters")
    return normalized


def _validate_pagination(per_page: int, page: int) -> None:
    if per_page < 1 or per_page > 80:
        raise ValueError("per_page must be between 1 and 80")
    if page < 1:
        raise ValueError("page must be at least 1")


def _best_video_file(video_files: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    mp4_files = [
        video_file for video_file in video_files if video_file.get("file_type") == "video/mp4"
    ]
    candidates = mp4_files or video_files
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda video_file: (
            video_file.get("quality") == "hd",
            video_file.get("width", 0),
            video_file.get("height", 0),
        ),
    )


def attribution_text(item: Dict[str, Any], kind: str = "Photo") -> str:
    name = item.get("photographer") or "a Pexels contributor"
    return f"{kind} by {name} on Pexels"


def _normalize_photo(photo: Dict[str, Any]) -> Dict[str, Any]:
    source = photo.get("src") or {}
    item = {
        "id": photo["id"],
        "url": photo.get("url"),
        "width": photo.get("width"),
        "height": photo.get("height"),
        "avg_color": photo.get("avg_color"),
        "alt": photo.get("alt"),
        "photographer": photo.get("photographer"),
        "photographer_url": photo.get("photographer_url"),
        "src": {
            "original": source.get("original"),
            "large": source.get("large"),
            "medium": source.get("medium"),
            "small": source.get("small"),
            "portrait": source.get("portrait"),
            "landscape": source.get("landscape"),
        },
    }
    item["attribution"] = attribution_text(item, "Photo")
    return item


def _normalize_video(video: Dict[str, Any]) -> Dict[str, Any]:
    user = video.get("user") or {}
    best_file = _best_video_file(video.get("video_files") or [])
    item = {
        "id": video["id"],
        "url": video.get("url"),
        "width": video.get("width"),
        "height": video.get("height"),
        "duration_seconds": video.get("duration"),
        "preview_image": video.get("image"),
        "photographer": user.get("name"),
        "photographer_url": user.get("url"),
        "video_url": best_file.get("link") if best_file else None,
        "video_quality": best_file.get("quality") if best_file else None,
        "video_width": best_file.get("width") if best_file else None,
        "video_height": best_file.get("height") if best_file else None,
    }
    item["attribution"] = attribution_text(item, "Video")
    return item


def search_pexels_photos(
    query: str,
    per_page: int = 15,
    page: int = 1,
    orientation: Optional[Orientation] = USE_DEFAULT,
    size: Optional[Size] = USE_DEFAULT,
) -> Dict[str, Any]:
    """Search Pexels for stock photos matching a query."""
    normalized = _normalize_query(query)
    _validate_pagination(per_page, page)
    orientation = _resolve(orientation, "orientation", ORIENTATIONS)
    size = _resolve(size, "size", SIZES)

    response = _request_json(
        PEXELS_PHOTOS_BASE,
        "/search",
        {
            "query": normalized,
            "per_page": per_page,
            "page": page,
            "orientation": orientation,
            "size": size,
        },
    )
    photos = [_normalize_photo(photo) for photo in response.get("photos") or []]
    if not photos:
        raise PexelsNotFoundError(f"No Pexels photos found for '{normalized}'")

    return {
        "query": normalized,
        "media_type": "photo",
        "orientation": orientation,
        "size": size,
        "page": response.get("page", page),
        "per_page": response.get("per_page", per_page),
        "total_results": response.get("total_results", len(photos)),
        "next_page": response.get("next_page"),
        "source": "Pexels",
        "attribution": "Photos provided by Pexels (https://www.pexels.com)",
        "photos": photos,
    }


def search_pexels_videos(
    query: str,
    per_page: int = 15,
    page: int = 1,
    orientation: Optional[Orientation] = USE_DEFAULT,
    size: Optional[Size] = USE_DEFAULT,
) -> Dict[str, Any]:
    """Search Pexels for stock videos matching a query."""
    normalized = _normalize_query(query)
    _validate_pagination(per_page, page)
    orientation = _resolve(orientation, "orientation", ORIENTATIONS)
    size = _resolve(size, "size", SIZES)

    response = _request_json(
        PEXELS_VIDEOS_BASE,
        "/search",
        {
            "query": normalized,
            "per_page": per_page,
            "page": page,
            "orientation": orientation,
            "size": size,
        },
    )
    videos = [_normalize_video(video) for video in response.get("videos") or []]
    if not videos:
        raise PexelsNotFoundError(f"No Pexels videos found for '{normalized}'")

    return {
        "query": normalized,
        "media_type": "video",
        "orientation": orientation,
        "size": size,
        "page": response.get("page", page),
        "per_page": response.get("per_page", per_page),
        "total_results": response.get("total_results", len(videos)),
        "next_page": response.get("next_page"),
        "source": "Pexels",
        "attribution": "Videos provided by Pexels (https://www.pexels.com)",
        "videos": videos,
    }


def search_pexels(
    query: str,
    media_type: Optional[MediaType] = None,
    per_page: int = 15,
    page: int = 1,
    orientation: Optional[Orientation] = USE_DEFAULT,
    size: Optional[Size] = USE_DEFAULT,
) -> Dict[str, Any]:
    """Search Pexels for stock photos, videos, or both (default: the saved media type)."""
    if media_type is None:
        media_type = _defaults().get("media_type") or "video"
    if media_type not in ("photo", "video", "both"):
        raise ValueError("media_type must be photo, video, or both")

    if media_type == "photo":
        return search_pexels_photos(
            query, per_page=per_page, page=page, orientation=orientation, size=size
        )
    if media_type == "video":
        return search_pexels_videos(
            query, per_page=per_page, page=page, orientation=orientation, size=size
        )

    photo_results = search_pexels_photos(
        query, per_page=per_page, page=page, orientation=orientation, size=size
    )
    video_results = search_pexels_videos(
        query, per_page=per_page, page=page, orientation=orientation, size=size
    )
    return {
        "query": photo_results["query"],
        "media_type": "both",
        "orientation": photo_results["orientation"],
        "size": photo_results["size"],
        "page": page,
        "per_page": per_page,
        "source": "Pexels",
        "attribution": "Media provided by Pexels (https://www.pexels.com)",
        "photos": photo_results["photos"],
        "videos": video_results["videos"],
        "photo_total_results": photo_results["total_results"],
        "video_total_results": video_results["total_results"],
    }
