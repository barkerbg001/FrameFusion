"""The four image tools (search, inspect, download, list) plus scene assignment.

One ``ImageToolkit`` lives for one run. It caches every candidate it has
returned, so ``inspect`` and ``download`` take a candidate ID and never a URL
chosen by the model: the model can only download what a search actually found.
Images with unknown reuse rights can only be downloaded when the user supplied
the URL themselves (or acts directly in the UI).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from engine.orchestrator.store import ProjectStore
from engine.runtime import record_tool_result, report
from engine.services.images import safe_fetch, sources
from engine.services.images.candidates import (
    MAX_IMAGE_BYTES,
    ImageCandidate,
    InvalidImage,
    ValidatedImage,
    validate_image,
    vertical_fit,
)

ORIENTATIONS = ("portrait", "landscape", "square")
SOURCES = ("auto", "pexels", "openverse", "url", "webpage")


class ImageToolError(Exception):
    def __init__(self, message: str, kind: str = "image_error") -> None:
        super().__init__(message)
        self.kind = kind


def _normalise_url(url: str) -> str:
    return url.strip().rstrip("/").lower()


class ImageToolkit:
    def __init__(
        self,
        store: ProjectStore,
        *,
        agent: str = "visual",
        user_urls: list[str] | None = None,
        allow_unknown_rights: bool = False,
        scene_count: int | None = None,
    ) -> None:
        self.store = store
        self.agent = agent
        self.user_urls = {_normalise_url(url) for url in (user_urls or [])}
        self.allow_unknown_rights = allow_unknown_rights
        self.scene_count = scene_count
        self.candidates: dict[str, ImageCandidate] = {}
        self.validated: dict[str, ValidatedImage] = {}
        self.assignments: dict[int, dict[str, Any]] = {}
        self.downloads: list[dict[str, Any]] = []
        self.limitations: list[str] = []
        self.calls = 0

    # -- operations -----------------------------------------------------

    def search(
        self,
        query: str,
        source: str = "auto",
        orientation: str = "portrait",
        limit: int = 8,
    ) -> dict[str, Any]:
        if source not in SOURCES:
            raise ImageToolError(f"source must be one of: {', '.join(SOURCES)}", "bad_request")
        chosen_orientation = orientation if orientation in ORIENTATIONS else None
        user_supplied = self.allow_unknown_rights or _normalise_url(query) in self.user_urls
        try:
            found, limitations = sources.search(
                query,
                source=source,  # type: ignore[arg-type]
                orientation=chosen_orientation,  # type: ignore[arg-type]
                limit=limit,
                user_supplied=user_supplied,
            )
        except sources.ImageSearchError as exc:
            raise ImageToolError(str(exc), exc.kind) from exc
        except safe_fetch.FetchError as exc:
            raise ImageToolError(str(exc), exc.kind) from exc
        for candidate in found:
            self.candidates[candidate.candidate_id] = candidate
        self.limitations.extend(item for item in limitations if item not in self.limitations)
        return {
            "query": query,
            "source": source,
            "count": len(found),
            "candidates": [candidate.summary() for candidate in found],
            "limitations": limitations,
        }

    def candidate(self, candidate_id: str) -> ImageCandidate:
        candidate = self.candidates.get(candidate_id.strip())
        if candidate is None:
            raise ImageToolError(
                "Unknown candidate_id. Use an ID returned by search_images in this run.",
                "not_found",
            )
        return candidate

    def _fetch(self, candidate: ImageCandidate) -> ValidatedImage:
        cached = self.validated.get(candidate.candidate_id)
        if cached is not None:
            return cached
        try:
            fetched = safe_fetch.fetch_bytes(
                candidate.download_url, max_bytes=MAX_IMAGE_BYTES, accept=("image/",)
            )
            image = validate_image(fetched.data)
        except safe_fetch.FetchError as exc:
            raise ImageToolError(str(exc), exc.kind) from exc
        except InvalidImage as exc:
            raise ImageToolError(str(exc), "invalid_image") from exc
        candidate.width, candidate.height, candidate.format = (
            image.width,
            image.height,
            image.format,
        )
        self.validated[candidate.candidate_id] = image
        return image

    def inspect(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.candidate(candidate_id)
        image = self._fetch(candidate)
        return {
            **candidate.summary(),
            "format": image.format,
            "bytes": image.size_bytes,
            "vertical_fit": vertical_fit(image.width, image.height),
            "license_url": candidate.license_url,
            "attribution": candidate.attribution,
            "usage_note": candidate.usage_note,
            "can_download": self._may_download(candidate),
        }

    def _may_download(self, candidate: ImageCandidate) -> bool:
        return (
            candidate.rights_status == "documented"
            or candidate.user_supplied
            or self.allow_unknown_rights
        )

    def _check_scene(self, scene_index: int | None) -> int | None:
        if scene_index is None or scene_index < 0:
            return None
        if self.scene_count is not None and scene_index >= self.scene_count:
            raise ImageToolError(
                f"scene_index must be between 0 and {self.scene_count - 1}.", "bad_request"
            )
        return scene_index

    def download(
        self, candidate_id: str, scene_index: int | None = None, reason: str = ""
    ) -> dict[str, Any]:
        candidate = self.candidate(candidate_id)
        scene = self._check_scene(scene_index)
        if not self._may_download(candidate):
            raise ImageToolError(
                "This image's reuse rights are unknown. Automatic selection only uses images "
                "with a documented licence (Pexels or Openverse). Ask the user to supply or "
                "approve it.",
                "rights_unknown",
            )
        image = self._fetch(candidate)
        asset = self.store.save_image(image, candidate, scene_index=scene)
        self.downloads.append(asset)
        if scene is not None:
            self.assignments[scene] = {
                "scene_index": scene,
                "asset_id": asset["id"],
                "candidate_id": candidate.candidate_id,
                "reason": reason[:300],
            }
        return {
            "asset_id": asset["id"],
            "reused_existing_file": bool(asset.get("reused")),
            "scene_index": scene,
            "width": image.width,
            "height": image.height,
            "license": candidate.license,
            "attribution": candidate.attribution,
        }

    def assign(self, scene_index: int, asset_id: str, reason: str = "") -> dict[str, Any]:
        scene = self._check_scene(scene_index)
        if scene is None:
            raise ImageToolError("scene_index is required.", "bad_request")
        asset = self.store.asset(asset_id.strip())
        if asset is None or asset.get("kind") != "image" or not asset.get("exists"):
            raise ImageToolError("That asset_id isn't an image in this project.", "not_found")
        self.assignments[scene] = {
            "scene_index": scene,
            "asset_id": asset["id"],
            "candidate_id": asset.get("candidate_id") or "",
            "reason": reason[:300],
        }
        return {"scene_index": scene, "asset_id": asset["id"]}

    def list_assets(self) -> dict[str, Any]:
        assets = self.store.list_assets(kind="image")
        return {
            "count": len(assets),
            "assets": [
                {
                    "asset_id": asset["id"],
                    "name": asset.get("name"),
                    "width": asset.get("width"),
                    "height": asset.get("height"),
                    "license": asset.get("license"),
                    "rights_status": asset.get("rights_status"),
                    "scene_index": asset.get("scene_index"),
                }
                for asset in assets
            ],
        }

    # -- model-facing tools ---------------------------------------------

    def _run(
        self, name: str, args: dict[str, Any], label: str, action: Callable[[], dict[str, Any]]
    ) -> str:
        self.calls += 1
        report("tool_start", tool=name, agent=self.agent, label=label)
        try:
            result = action()
        except ImageToolError as exc:
            record_tool_result(name, args, error=str(exc), agent=self.agent)
            return json.dumps({"error": str(exc), "kind": exc.kind})
        except ValueError as exc:
            record_tool_result(name, args, error=str(exc), agent=self.agent)
            return json.dumps({"error": str(exc), "kind": "bad_request"})
        record_tool_result(name, args, result, agent=self.agent)
        return json.dumps(result)

    def tools(self) -> list[Callable[..., str]]:
        toolkit = self

        def search_images(
            query: str, source: str = "auto", orientation: str = "portrait", limit: int = 8
        ) -> str:
            """Search for images. Results are candidates with licence information.

            Args:
                query: Short visual search phrase, e.g. "tide pool sea anemone close up".
                    For source "url" or "webpage" pass the exact URL the user supplied.
                source: auto (Pexels and Openverse), pexels, openverse, url (a direct image URL
                    from the user) or webpage (extract images from a public page the user gave).
                orientation: portrait, landscape or square. Prefer portrait for 9:16 video.
                limit: Maximum number of candidates, 1 to 20.
            """
            args = {"query": query, "source": source, "orientation": orientation, "limit": limit}
            return toolkit._run(
                "search_images",
                args,
                f"Searching {source} images for “{query[:60]}”",
                lambda: toolkit.search(query, source, orientation, limit),
            )

        def inspect_image_candidate(candidate_id: str) -> str:
            """Fetch and validate a candidate: real dimensions, format, 9:16 fit and licence.

            Args:
                candidate_id: An ID returned by search_images.
            """
            return toolkit._run(
                "inspect_image_candidate",
                {"candidate_id": candidate_id},
                "Inspecting an image",
                lambda: toolkit.inspect(candidate_id),
            )

        def download_image(candidate_id: str, scene_index: int = -1, reason: str = "") -> str:
            """Download a candidate into the project and optionally assign it to a scene.

            Args:
                candidate_id: An ID returned by search_images.
                scene_index: Zero-based scene this image illustrates, or -1 for none.
                reason: One short sentence on why it fits the scene.
            """
            args = {"candidate_id": candidate_id, "scene_index": scene_index}
            return toolkit._run(
                "download_image",
                args,
                f"Downloading an image for scene {scene_index + 1}"
                if scene_index >= 0
                else "Downloading an image",
                lambda: toolkit.download(candidate_id, scene_index, reason),
            )

        def list_project_assets() -> str:
            """List images already in this project (reuse them instead of re-downloading)."""
            return toolkit._run(
                "list_project_assets", {}, "Listing project images", toolkit.list_assets
            )

        def assign_scene_image(scene_index: int, asset_id: str, reason: str = "") -> str:
            """Assign an image that is already in the project to a scene.

            Args:
                scene_index: Zero-based scene index.
                asset_id: An asset_id from list_project_assets or download_image.
                reason: One short sentence on why it fits.
            """
            args = {"scene_index": scene_index, "asset_id": asset_id}
            return toolkit._run(
                "assign_scene_image",
                args,
                f"Assigning an image to scene {scene_index + 1}",
                lambda: toolkit.assign(scene_index, asset_id, reason),
            )

        return [
            search_images,
            inspect_image_candidate,
            download_image,
            list_project_assets,
            assign_scene_image,
        ]
