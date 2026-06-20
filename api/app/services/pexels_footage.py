import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.services.pexels_client import (
    PexelsNotFoundError,
    search_pexels_photos,
    search_pexels_videos,
)


GENERATED_DIR = Path("generated")
PEXELS_CACHE_DIR = GENERATED_DIR / "pexels_cache"


class PexelsFootageError(Exception):
    pass


def _guess_suffix(url: str, media_type: str) -> str:
    path = urlparse(url).path.lower()
    for suffix in (".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".webp"):
        if path.endswith(suffix):
            return suffix
    return ".mp4" if media_type == "video" else ".jpg"


def download_pexels_media(url: str, media_type: str) -> Path:
    """Download a Pexels photo or video file to the local cache."""
    normalized_url = url.strip()
    if not normalized_url:
        raise ValueError("url must not be blank")

    PEXELS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = _guess_suffix(normalized_url, media_type)
    destination = PEXELS_CACHE_DIR / f"{uuid.uuid4().hex}{suffix}"
    request = Request(
        normalized_url,
        headers={"User-Agent": "FrameFusion/1.0 (Pexels media download)"},
    )

    try:
        with urlopen(request, timeout=120) as response:
            destination.write_bytes(response.read())
    except (HTTPError, URLError, TimeoutError) as exc:
        raise PexelsFootageError(
            f"Unable to download Pexels media: {exc}"
        ) from exc

    if not destination.is_file() or destination.stat().st_size == 0:
        raise PexelsFootageError("Downloaded Pexels media file is empty")
    return destination


def _footage_from_pexels_result(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    videos = result.get("videos") or []
    for video in videos:
        video_url = video.get("video_url")
        if video_url:
            return {
                "url": video_url,
                "media_type": "video",
                "photographer": video.get("photographer"),
                "query": result.get("query"),
            }

    photos = result.get("photos") or []
    for photo in photos:
        source = photo.get("src") or {}
        photo_url = (
            source.get("portrait")
            or source.get("large")
            or source.get("medium")
            or source.get("original")
        )
        if photo_url:
            return {
                "url": photo_url,
                "media_type": "photo",
                "photographer": photo.get("photographer"),
                "query": result.get("query"),
            }
    return None


def _footage_from_recommended_media(
    recommended_media: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    for item in recommended_media:
        media_type = (item.get("media_type") or "").lower()
        download_url = item.get("download_url") or item.get("url")
        if not download_url:
            continue
        if media_type == "video" and download_url.lower().endswith(".mp4"):
            return {
                "url": download_url,
                "media_type": "video",
                "photographer": item.get("photographer"),
            }
        if media_type in {"photo", "image"}:
            return {
                "url": download_url,
                "media_type": "photo",
                "photographer": item.get("photographer"),
            }
    return None


def resolve_pexels_footage(
    recommended_media: Optional[List[Dict[str, Any]]] = None,
    research_data: Optional[Dict[str, Any]] = None,
    fallback_query: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Pick the best downloadable Pexels clip from research output or search."""
    if recommended_media:
        selected = _footage_from_recommended_media(recommended_media)
        if selected:
            return selected

    for call in (research_data or {}).get("tool_calls") or []:
        if call.get("tool") != "pexels":
            continue
        result = call.get("result")
        if not isinstance(result, dict):
            continue
        selected = _footage_from_pexels_result(result)
        if selected:
            return selected

    query = " ".join((fallback_query or "").strip().split())
    if len(query) < 2:
        return None

    try:
        return _footage_from_pexels_result(
            search_pexels_videos(query, per_page=3)
        )
    except PexelsNotFoundError:
        try:
            return _footage_from_pexels_result(
                search_pexels_photos(
                    query,
                    per_page=3,
                    orientation="portrait",
                )
            )
        except PexelsNotFoundError:
            return None


def prepare_pexels_background(
    recommended_media: Optional[List[Dict[str, Any]]] = None,
    research_data: Optional[Dict[str, Any]] = None,
    fallback_query: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve and download Pexels footage for use as a video background."""
    footage = resolve_pexels_footage(
        recommended_media=recommended_media,
        research_data=research_data,
        fallback_query=fallback_query,
    )
    if footage is None:
        return None

    local_path = download_pexels_media(
        footage["url"],
        footage["media_type"],
    )
    return {
        **footage,
        "local_path": str(local_path.resolve()),
    }


def download_pexels_clips(query: str, clip_count: int) -> Dict[str, Any]:
    """Search Pexels and download multiple clips to the local cache."""
    normalized = " ".join(query.strip().split())
    if len(normalized) < 2:
        raise ValueError("query must contain at least two characters")
    if clip_count < 1 or clip_count > 8:
        raise ValueError("clip_count must be between 1 and 8")

    clips: List[Dict[str, Any]] = []

    try:
        video_results = search_pexels_videos(
            normalized,
            per_page=min(max(clip_count * 2, clip_count), 15),
        )
        for video in video_results.get("videos") or []:
            if len(clips) >= clip_count:
                break
            video_url = video.get("video_url")
            if not video_url:
                continue
            local_path = download_pexels_media(video_url, "video")
            clips.append(
                {
                    "clip_id": local_path.stem,
                    "local_path": str(local_path.resolve()),
                    "media_type": "video",
                    "photographer": video.get("photographer"),
                    "pexels_url": video.get("url"),
                    "duration_seconds": video.get("duration_seconds"),
                }
            )
    except PexelsNotFoundError:
        pass

    if len(clips) < clip_count:
        try:
            photo_results = search_pexels_photos(
                normalized,
                per_page=min(max(clip_count * 2, clip_count), 15),
                orientation="portrait",
            )
            for photo in photo_results.get("photos") or []:
                if len(clips) >= clip_count:
                    break
                source = photo.get("src") or {}
                photo_url = (
                    source.get("portrait")
                    or source.get("large")
                    or source.get("medium")
                    or source.get("original")
                )
                if not photo_url:
                    continue
                local_path = download_pexels_media(photo_url, "photo")
                clips.append(
                    {
                        "clip_id": local_path.stem,
                        "local_path": str(local_path.resolve()),
                        "media_type": "photo",
                        "photographer": photo.get("photographer"),
                        "pexels_url": photo.get("url"),
                        "duration_seconds": None,
                    }
                )
        except PexelsNotFoundError:
            pass

    if not clips:
        raise PexelsFootageError(
            f"No Pexels clips could be downloaded for '{normalized}'"
        )

    stitch_payload = [
        {"local_path": clip["local_path"], "media_type": clip["media_type"]}
        for clip in clips
    ]
    return {
        "query": normalized,
        "clip_count": len(clips),
        "clips": clips,
        "clips_json": json.dumps(stitch_payload),
        "attribution": "Footage from Pexels (https://www.pexels.com). Credit photographers when publishing.",
    }
