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
from pathlib import PurePath
from types import SimpleNamespace
from typing import Any

from django.core.files.uploadedfile import UploadedFile
from pydantic import ValidationError

from engine.runtime import report
from engine.services.images import pasted, safe_fetch
from engine.services.images.brief import VisualBrief, derive_brief
from engine.services.images.candidates import (
    MAX_IMAGE_BYTES,
    ImageCandidate,
    InvalidImage,
    clean_text,
    difference_hash,
    validate_image,
)
from engine.services.images.relevance import VisionJudge, decide, technical_problems
from engine.services.images.toolkit import ImageToolError, ImageToolkit

from .models import MediaAsset, ProductionTask, Project
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


def scene_brief(project: Project, scene_index: int) -> VisualBrief | None:
    """The brief the visual specialist wrote for a scene, or one derived from the script."""
    latest: dict[str, ProductionTask] = {}
    for task in ProductionTask.objects.filter(
        project=project, stage__in=("script", "visuals")
    ).order_by("created_at"):
        latest[task.stage] = task
    visuals = latest.get("visuals")
    for state in ((visuals.output or {}).get("scenes") or []) if visuals else []:
        if state.get("scene_index") == scene_index and isinstance(state.get("brief"), dict):
            try:
                return VisualBrief.model_validate(state["brief"])
            except ValidationError:
                break
    script = latest.get("script")
    scenes = ((script.output or {}).get("scenes") or []) if script else []
    if not 0 <= scene_index < len(scenes):
        return None
    scene = scenes[scene_index]
    try:
        return derive_brief(
            SimpleNamespace(
                index=scene_index,
                visual_description=scene.get("visual_description") or "",
                narration=scene.get("narration") or "",
                image_query=scene.get("image_query") or scene.get("visual_description") or "",
            )
        )
    except ValidationError:
        return None


def _resolve_link(query: str, limit: int) -> tuple[dict[str, ImageCandidate], list[str]]:
    try:
        found, notes = pasted.resolve(query, limit=limit)
    except pasted.PastedLinkError as exc:
        raise ImageToolError(str(exc), exc.kind) from exc
    except safe_fetch.FetchError as exc:
        raise ImageToolError(str(exc), exc.kind) from exc
    return {candidate.candidate_id: candidate for candidate in found}, notes


def search(
    project: Project,
    query: str,
    source: str,
    orientation: str,
    limit: int,
    scene_index: int | None = None,
) -> dict[str, Any]:
    if source == "link":
        by_id, notes = _resolve_link(query, limit)
        result: dict[str, Any] = {
            "query": query,
            "source": source,
            "count": len(by_id),
            "limitations": notes,
        }
        ordered = list(by_id.values())
    else:
        toolkit = _toolkit(project)
        result = toolkit.search(query, source, orientation, limit)
        by_id = toolkit.candidates
        ordered = [by_id[item["candidate_id"]] for item in result["candidates"]]
    _remember(str(project.pk), by_id)
    brief = scene_brief(project, scene_index) if scene_index is not None else None
    items = []
    for candidate in ordered:
        item = candidate.public()
        if brief is not None:
            # Free metadata check; the vision check is a separate job you start yourself.
            item["assessment"] = decide(candidate, brief, None).model_dump()
        items.append(item)
    result["candidates"] = items
    return result


MAX_CHECK_CANDIDATES = 6


def check_input(project: Project, scene_index: int, candidate_ids: list[str]) -> dict[str, Any]:
    """Job input for a vision check of search results; candidates are copied from the cache."""
    if scene_brief(project, scene_index) is None:
        raise ValueError("That scene has no script yet.")
    candidates = []
    for candidate_id in dict.fromkeys(candidate_ids):
        candidate = _recall(str(project.pk), candidate_id) or _persisted_alternative(
            project, candidate_id
        )
        if candidate is None:
            raise ValueError("Those search results have expired. Search again.")
        candidates.append(candidate.model_dump())
    if not candidates:
        raise ValueError("Choose at least one image to check.")
    return {"scene_index": scene_index, "candidates": candidates[:MAX_CHECK_CANDIDATES]}


def run_check(project: Project, payload: dict[str, Any]) -> dict[str, Any]:
    """Check candidates against the scene's brief with the Visual specialist model."""
    scene_index = int(payload["scene_index"])
    brief = scene_brief(project, scene_index)
    if brief is None:
        raise ValueError("That scene has no script yet.")
    candidates = [ImageCandidate.model_validate(item) for item in payload.get("candidates") or []]
    _remember(str(project.pk), {c.candidate_id: c for c in candidates})
    judge = VisionJudge("visual", max_calls=1)
    visual = [c for c in candidates if not technical_problems(c, brief)]
    report("step", agent="visual", status="running")
    verdicts, problems = judge.assess(brief, visual)
    report("step", agent="visual", status="done")
    note = judge.note or "Not inspected visually."
    return {
        "scene_index": scene_index,
        "vision_available": judge.available and bool(verdicts),
        "assessments": [
            decide(
                candidate,
                brief,
                verdicts.get(candidate.candidate_id),
                vision_note=problems.get(candidate.candidate_id, note),
            ).model_dump()
            for candidate in candidates
        ],
        "limitations": judge.limitations,
    }


def _persisted_alternative(project: Project, candidate_id: str) -> ImageCandidate | None:
    """Candidates the visual specialist assessed are stored with the visuals stage."""
    task = (
        ProductionTask.objects.filter(project=project, stage="visuals")
        .order_by("-created_at")
        .first()
    )
    for state in ((task.output or {}).get("scenes") or []) if task else []:
        for item in state.get("alternatives") or []:
            if item.get("candidate_id") == candidate_id and isinstance(item.get("candidate"), dict):
                try:
                    return ImageCandidate.model_validate(item["candidate"])
                except ValidationError:
                    return None
    return None


def download(
    project: Project, candidate_id: str, scene_index: int | None, *, illustrative: bool = False
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    candidate = _recall(str(project.pk), candidate_id) or _persisted_alternative(
        project, candidate_id
    )
    if candidate is None:
        raise ValueError("That search result has expired. Search again.")
    toolkit = _toolkit(project)
    toolkit.candidates[candidate.candidate_id] = candidate
    saved = toolkit.download(
        candidate.candidate_id, None, "Chosen by you", metadata={"chosen_by_user": True}
    )
    visuals = None
    if scene_index is not None:
        asset = MediaAsset.objects.get(pk=saved["asset_id"])
        visuals = replace_scene_asset(project, scene_index, asset, illustrative=illustrative)
    return saved, visuals


def upload(
    project: Project, file: UploadedFile, scene_index: int | None
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if file.size is not None and file.size > MAX_IMAGE_BYTES:
        raise ImageToolError("The image is larger than 15 MB.", "too_large")
    data = file.read(MAX_IMAGE_BYTES + 1)
    try:
        image = validate_image(data)
    except InvalidImage as exc:
        raise ImageToolError(str(exc), "invalid_image") from exc
    name = clean_text(PurePath(file.name or "upload").name, 120)
    candidate = ImageCandidate(
        candidate_id=f"upload:{image.sha256[:16]}",
        provider="upload",
        title=name.rsplit(".", 1)[0] or "upload",
        download_url="upload://local",
        rights_status="unknown",
        usage_note="Uploaded by you. Only use it if you own it or have permission.",
        user_supplied=True,
        width=image.width,
        height=image.height,
        format=image.format,
    )
    store = DjangoProjectStore(project)
    asset_record = store.save_image(
        image,
        candidate,
        scene_index=None,
        metadata={"dhash": difference_hash(image.data), "chosen_by_user": True},
    )
    saved = {
        "asset_id": asset_record["id"],
        "reused_existing_file": bool(asset_record.get("reused")),
    }
    visuals = None
    if scene_index is not None:
        asset = MediaAsset.objects.get(pk=saved["asset_id"])
        visuals = replace_scene_asset(project, scene_index, asset)
    return saved, visuals
