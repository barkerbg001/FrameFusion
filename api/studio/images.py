"""Image search and download for the user, from the project's Scenes tab.

The browser never sends image metadata back: it gets candidate IDs from a
search and downloads by ID, so licence and source details always come from the
provider response the server saw. Candidates are cached per project in memory
for an hour (single-process server, like the job runner).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

from engine.services.images.candidates import ImageCandidate
from engine.services.images.toolkit import ImageToolkit

from .models import MediaAsset, Project
from .store import DjangoProjectStore, replace_scene_asset

CACHE_SECONDS = 3600
CACHE_LIMIT = 600

_lock = threading.Lock()
_cache: OrderedDict[tuple[str, str], tuple[float, ImageCandidate]] = OrderedDict()


def _remember(project_id: str, candidates: dict[str, ImageCandidate]) -> None:
    now = time.monotonic()
    with _lock:
        for candidate_id, candidate in candidates.items():
            _cache[(project_id, candidate_id)] = (now, candidate)
            _cache.move_to_end((project_id, candidate_id))
        while len(_cache) > CACHE_LIMIT:
            _cache.popitem(last=False)


def _recall(project_id: str, candidate_id: str) -> ImageCandidate | None:
    with _lock:
        entry = _cache.get((project_id, candidate_id))
    if entry is None or time.monotonic() - entry[0] > CACHE_SECONDS:
        return None
    return entry[1]


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _toolkit(project: Project) -> ImageToolkit:
    # The user is choosing directly, so images with unknown rights may be saved; they keep
    # rights_status "unknown" and the UI says so.
    return ImageToolkit(DjangoProjectStore(project), agent="user", allow_unknown_rights=True)


def search(
    project: Project, query: str, source: str, orientation: str, limit: int
) -> dict[str, Any]:
    toolkit = _toolkit(project)
    result = toolkit.search(query, source, orientation, limit)
    _remember(str(project.pk), toolkit.candidates)
    by_id = toolkit.candidates
    result["candidates"] = [
        {
            **summary,
            "preview_url": by_id[summary["candidate_id"]].preview_url,
            "source_page_url": by_id[summary["candidate_id"]].source_page_url,
            "creator_url": by_id[summary["candidate_id"]].creator_url,
            "license_url": by_id[summary["candidate_id"]].license_url,
            "attribution": by_id[summary["candidate_id"]].attribution,
            "usage_note": by_id[summary["candidate_id"]].usage_note,
        }
        for summary in result["candidates"]
    ]
    return result


def download(
    project: Project, candidate_id: str, scene_index: int | None
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    candidate = _recall(str(project.pk), candidate_id)
    if candidate is None:
        raise ValueError("That search result has expired. Search again.")
    toolkit = _toolkit(project)
    toolkit.candidates[candidate.candidate_id] = candidate
    saved = toolkit.download(candidate.candidate_id, None, "Chosen by you")
    visuals = None
    if scene_index is not None:
        asset = MediaAsset.objects.get(pk=saved["asset_id"])
        visuals = replace_scene_asset(project, scene_index, asset)
    return saved, visuals
