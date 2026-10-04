"""Image tools for the visual specialist, plus the user's direct search and download.

One ``ImageToolkit`` lives for one run. It caches every candidate it returned,
so inspection and download take a candidate ID and never a URL chosen by the
model: the model can only download what a search actually found.

Per scene the specialist works from a visual brief:

1. ``build_visual_brief`` - read (or carefully refine) what the image must show.
2. ``search_image_sources`` - bounded, subject-preserving queries per source.
3. ``inspect_image_candidates`` - previews checked by the vision model (or by
   metadata when the model can't see images) against the brief.
4. ``rank_image_candidates`` - accepted, needs-review and illustrative lists.
5. ``download_and_register_image`` - only candidates whose assessment is
   ``accept``; the file is validated, de-duplicated and stored with provenance.
6. ``list_project_assets`` and ``report_visual_gap`` - reuse and honest gaps.

Nothing is ever selected because it was the first result or because a download
succeeded. Scenes without an accepted image stay unresolved with next actions.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from engine.orchestrator.schemas import GapAction, SceneAsset, SceneGap, SceneVisual
from engine.orchestrator.store import ProjectStore
from engine.runtime import check_cancelled, record_tool_result, report
from engine.services.images import safe_fetch, sources
from engine.services.images.brief import MAX_QUERIES, VisualBrief, query_problem
from engine.services.images.candidates import (
    MAX_IMAGE_BYTES,
    NEAR_DUPLICATE_BITS,
    ImageCandidate,
    InvalidImage,
    ValidatedImage,
    difference_hash,
    hash_distance,
    validate_image,
    vertical_fit,
)
from engine.services.images.relevance import (
    CandidateAssessment,
    VisionJudge,
    decide,
    metadata_signals,
    technical_problems,
)

ORIENTATIONS = ("portrait", "landscape", "square")
SOURCES = sources.SEARCH_SOURCES
MAX_SEARCHES_PER_SCENE = 5
MAX_INSPECTED_PER_SCENE = 12
MAX_INSPECT_BATCH = 6
MAX_DOWNLOAD_ATTEMPTS_PER_SCENE = 3
MAX_ALTERNATIVES = 6
DECISION_ORDER = {"accept": 0, "review": 1, "illustrative": 2, "reject": 3}
SPECIFICITY_RANK = {"generic": 0, "representative": 1, "exact": 2}


class ImageToolError(Exception):
    def __init__(self, message: str, kind: str = "image_error") -> None:
        super().__init__(message)
        self.kind = kind


def _normalise_url(url: str) -> str:
    return url.strip().rstrip("/").lower()


@dataclass
class SceneWork:
    brief: VisualBrief
    searches: list[dict[str, Any]] = field(default_factory=list)
    candidate_ids: list[str] = field(default_factory=list)
    assessments: dict[str, CandidateAssessment] = field(default_factory=dict)
    download_failures: list[str] = field(default_factory=list)
    selected: SceneAsset | None = None
    gap: SceneGap | None = None
    used_brave: bool = False


class ImageToolkit:
    def __init__(
        self,
        store: ProjectStore,
        *,
        agent: str = "visual",
        user_urls: list[str] | None = None,
        allow_unknown_rights: bool = False,
        scene_count: int | None = None,
        briefs: list[VisualBrief] | None = None,
        vision: VisionJudge | None = None,
    ) -> None:
        self.store = store
        self.agent = agent
        self.user_urls = {_normalise_url(url) for url in (user_urls or [])}
        self.allow_unknown_rights = allow_unknown_rights
        self.scene_count = scene_count
        self.vision = vision
        self.candidates: dict[str, ImageCandidate] = {}
        self.validated: dict[str, ValidatedImage] = {}
        self.work: dict[int, SceneWork] = {
            brief.scene_index: SceneWork(brief) for brief in briefs or []
        }
        self.used_hashes: dict[int, str] = {}
        self.used_assets: dict[str, int] = {}
        self.downloads: list[dict[str, Any]] = []
        self.limitations: list[str] = []
        self.calls = 0

    # -- shared plumbing ----------------------------------------------------

    def candidate(self, candidate_id: str) -> ImageCandidate:
        candidate = self.candidates.get(candidate_id.strip())
        if candidate is None:
            raise ImageToolError(
                "Unknown candidate_id. Use an ID returned by a search in this run.", "not_found"
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

    def _work(self, scene_index: int) -> SceneWork:
        scene = self._check_scene(scene_index)
        work = self.work.get(scene) if scene is not None else None
        if work is None:
            raise ImageToolError(
                "That scene isn't assigned to you in this run (or already has an image).",
                "bad_request",
            )
        return work

    def _note(self, items: list[str]) -> None:
        self.limitations.extend(item for item in items if item not in self.limitations)

    def reserve(self, scene_index: int, asset: dict[str, Any]) -> None:
        """Mark an image kept from an earlier run so no other scene repeats it."""
        self.used_assets.setdefault(asset["id"], scene_index)
        if asset.get("dhash"):
            self.used_hashes[scene_index] = str(asset["dhash"])

    def _duplicate_of(self, scene_index: int, image_hash: str, asset_id: str | None) -> int | None:
        if asset_id is not None and self.used_assets.get(asset_id, scene_index) != scene_index:
            return self.used_assets[asset_id]
        for other, other_hash in self.used_hashes.items():
            if (
                other != scene_index
                and hash_distance(image_hash, other_hash) <= NEAR_DUPLICATE_BITS
            ):
                return other
        return None

    # -- user operations (Scenes tab) --------------------------------------

    def search(
        self, query: str, source: str = "auto", orientation: str = "portrait", limit: int = 8
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
        self._note(limitations)
        return {
            "query": query,
            "source": source,
            "count": len(found),
            "candidates": [candidate.summary() for candidate in found],
            "limitations": limitations,
        }

    def inspect(self, candidate_id: str) -> dict[str, Any]:
        """Technical check of the full file (dimensions, format, 9:16 fit, licence)."""
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

    def download(
        self,
        candidate_id: str,
        scene_index: int | None = None,
        reason: str = "",
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        candidate = self.candidate(candidate_id)
        scene = self._check_scene(scene_index)
        if not self._may_download(candidate):
            raise ImageToolError(
                "This image's reuse rights are unknown. Automatic selection only uses images "
                "with a documented licence. It is offered to the user for review instead.",
                "rights_unknown",
            )
        image = self._fetch(candidate)
        image_hash = difference_hash(image.data)
        asset = self.store.save_image(
            image,
            candidate,
            scene_index=scene,
            metadata={**(metadata or {}), "dhash": image_hash},
        )
        self.downloads.append(asset)
        return {
            "asset_id": asset["id"],
            "reused_existing_file": bool(asset.get("reused")),
            "scene_index": scene,
            "width": image.width,
            "height": image.height,
            "license": candidate.license,
            "attribution": candidate.attribution,
            "dhash": image_hash,
            "reason": reason[:300],
        }

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
                    "used_by_scene": self.used_assets.get(asset["id"]),
                }
                for asset in assets
            ],
        }

    # -- scene operations (visual specialist) ------------------------------

    def brief(self, scene_index: int) -> dict[str, Any]:
        work = self._work(scene_index)
        return {
            **work.brief.summary(),
            "searches_used": len(work.searches),
            "searches_left": MAX_SEARCHES_PER_SCENE - len(work.searches),
        }

    def refine_brief(
        self,
        scene_index: int,
        *,
        subject: str = "",
        specificity: str = "",
        named_entities: str = "",
        visual_type: str = "",
        excluded: str = "",
        queries: str = "",
    ) -> dict[str, Any]:
        """Tighten a brief. Refinements may add detail but never drop the subject."""
        work = self._work(scene_index)
        current = work.brief
        data = current.model_dump()
        if subject.strip():
            proposed = VisualBrief.model_validate({**data, "subject": subject.strip()[:120]})
            new_terms = set(proposed.subject_terms)
            keeps_subject = (
                not current.subject_terms
                or bool(new_terms & set(current.subject_terms))
                or any(e.terms and set(e.terms) <= new_terms for e in current.named_entities)
            )
            if not keeps_subject:
                raise ImageToolError(
                    "A refined subject must keep the scene's subject (shared key words).",
                    "query_drops_subject",
                )
            data["subject"] = proposed.subject
        if named_entities.strip():
            extra = []
            for item in named_entities.split(";"):
                name, _, kind = item.partition(":")
                if name.strip():
                    extra.append({"name": name.strip()[:80], "kind": kind.strip() or "other"})
            data["named_entities"] = (data["named_entities"] + extra)[:4]
        if specificity.strip():
            value = specificity.strip()
            if value not in SPECIFICITY_RANK:
                raise ImageToolError(
                    "specificity must be exact, representative or generic.", "bad_request"
                )
            if (
                SPECIFICITY_RANK[value] < SPECIFICITY_RANK[current.specificity]
                and data["named_entities"]
            ):
                raise ImageToolError(
                    "The scene names a specific subject, so its specificity can't be loosened.",
                    "bad_request",
                )
            data["specificity"] = value
        if visual_type.strip():
            data["visual_type"] = visual_type.strip()
        if excluded.strip():
            extra_excluded = [item.strip()[:60] for item in excluded.split(",") if item.strip()]
            data["excluded"] = list(dict.fromkeys(data["excluded"] + extra_excluded))[:6]
        if queries.strip():
            data["queries"] = [
                {"query": item.strip()[:100], "rationale": "Refined by the visual specialist."}
                for item in queries.split("|")
                if item.strip()
            ][:MAX_QUERIES]
        try:
            refined = VisualBrief.model_validate(data)
        except ValidationError as exc:
            raise ImageToolError(
                f"Invalid brief refinement: {exc.errors()[0]['msg']}", "bad_request"
            ) from exc
        for query in refined.queries:
            problem = query_problem(query.query, refined)
            if problem:
                raise ImageToolError(f"“{query.query}”: {problem}", "query_drops_subject")
        work.brief = refined
        return self.brief(scene_index)

    def _orientation_for(self, brief: VisualBrief) -> str | None:
        if brief.specificity == "generic" and brief.orientation in ORIENTATIONS:
            return brief.orientation
        return None

    def scene_search(
        self,
        scene_index: int,
        query: str,
        source: str = "auto",
        limit: int = 8,
        rationale: str = "",
    ) -> dict[str, Any]:
        work = self._work(scene_index)
        brief = work.brief
        query = " ".join((query or "").split())
        if len(work.searches) >= MAX_SEARCHES_PER_SCENE:
            raise ImageToolError(
                "This scene's search budget is used up. Rank what you have or report the gap.",
                "budget_exhausted",
            )
        if source not in SOURCES:
            raise ImageToolError(f"source must be one of: {', '.join(SOURCES)}", "bad_request")
        user_url = _normalise_url(query) in self.user_urls
        if source in ("url", "webpage"):
            if not (user_url or self.allow_unknown_rights):
                raise ImageToolError(
                    "url and webpage sources only take a URL the user supplied.", "bad_request"
                )
        else:
            problem = query_problem(query, brief)
            if problem:
                raise ImageToolError(problem, "query_drops_subject")
        if source == "brave":
            if work.used_brave:
                raise ImageToolError(
                    "Brave image search is limited to one search per scene.", "budget_exhausted"
                )
            if not work.searches or any(a.decision == "accept" for a in work.assessments.values()):
                raise ImageToolError(
                    "Use Brave only after the licensed sources found nothing acceptable.",
                    "bad_request",
                )
            work.used_brave = True
        record: dict[str, Any] = {"query": query, "source": source, "rationale": rationale[:200]}
        work.searches.append(record)
        try:
            found, limitations = sources.search(
                query,
                source=source,  # type: ignore[arg-type]
                orientation=self._orientation_for(brief),  # type: ignore[arg-type]
                limit=max(1, min(limit, 12)),
                user_supplied=user_url or self.allow_unknown_rights,
                brief=brief,
            )
        except (sources.ImageSearchError, safe_fetch.FetchError) as exc:
            record.update(count=0, error=str(exc))
            raise ImageToolError(str(exc), exc.kind) from exc
        self._note(limitations)
        results = []
        for candidate in found:
            self.candidates.setdefault(candidate.candidate_id, candidate)
            if candidate.candidate_id not in work.candidate_ids:
                work.candidate_ids.append(candidate.candidate_id)
            signals = metadata_signals(candidate, brief)
            results.append(
                {
                    **candidate.summary(),
                    "metadata_names_subject": signals.entity_hits,
                    "metadata_subject_words": signals.anchor_hits,
                    "problems": technical_problems(candidate, brief),
                }
            )
        record["count"] = len(found)
        return {
            "scene_index": scene_index,
            "query": query,
            "source": source,
            "count": len(found),
            "candidates": results,
            "limitations": limitations,
            "searches_left": MAX_SEARCHES_PER_SCENE - len(work.searches),
            "note": "Metadata is a hint only. Inspect candidates before choosing one.",
        }

    def scene_inspect(self, scene_index: int, candidate_ids: list[str]) -> dict[str, Any]:
        work = self._work(scene_index)
        wanted = []
        for candidate_id in candidate_ids:
            candidate_id = candidate_id.strip()
            if not candidate_id or candidate_id in wanted:
                continue
            if candidate_id not in work.candidate_ids:
                raise ImageToolError(
                    f"{candidate_id} wasn't found by a search for this scene.", "not_found"
                )
            if candidate_id not in work.assessments:
                wanted.append(candidate_id)
        remaining = MAX_INSPECTED_PER_SCENE - len(work.assessments)
        if remaining <= 0 and wanted:
            raise ImageToolError(
                "This scene's inspection budget is used up. Rank what you have or report the gap.",
                "budget_exhausted",
            )
        wanted = wanted[: min(MAX_INSPECT_BATCH, remaining)]
        batch = [self.candidates[candidate_id] for candidate_id in wanted]
        visual = [c for c in batch if not technical_problems(c, work.brief)]
        verdicts: dict[str, Any] = {}
        problems: dict[str, str] = {}
        if self.vision is not None and visual:
            check_cancelled()
            verdicts, problems = self.vision.assess(work.brief, visual)
            self._note(self.vision.limitations)
        note = (
            self.vision.note
            if self.vision is not None
            else "Visual checks are off for this search."
        )
        for candidate in batch:
            work.assessments[candidate.candidate_id] = decide(
                candidate,
                work.brief,
                verdicts.get(candidate.candidate_id),
                vision_note=problems.get(candidate.candidate_id, note),
            )
        return {
            "scene_index": scene_index,
            "vision_available": bool(self.vision and self.vision.available),
            "assessments": [work.assessments[cid].model_dump() for cid in wanted],
            "inspections_left": MAX_INSPECTED_PER_SCENE - len(work.assessments),
        }

    def _ranked(self, work: SceneWork) -> list[CandidateAssessment]:
        return sorted(
            work.assessments.values(), key=lambda a: (DECISION_ORDER[a.decision], -a.score)
        )

    def scene_rank(self, scene_index: int) -> dict[str, Any]:
        work = self._work(scene_index)
        ranked = self._ranked(work)

        def view(items: list[CandidateAssessment]) -> list[dict[str, Any]]:
            return [
                {
                    "candidate_id": a.candidate_id,
                    "score": a.score,
                    "verification": a.verification,
                    "reasons": a.reasons,
                    "rights": a.rights,
                }
                for a in items
            ]

        accepted = [a for a in ranked if a.decision == "accept"]
        return {
            "scene_index": scene_index,
            "accepted": view(accepted),
            "needs_review": view([a for a in ranked if a.decision == "review"]),
            "illustrative_only": view([a for a in ranked if a.decision == "illustrative"]),
            "rejected_count": sum(1 for a in ranked if a.decision == "reject"),
            "not_inspected": [cid for cid in work.candidate_ids if cid not in work.assessments][
                :10
            ],
            "recommendation": accepted[0].candidate_id if accepted else None,
            "note": "Scores order candidates; they are heuristics, not probabilities.",
        }

    def scene_download(
        self, scene_index: int, candidate_id: str, reason: str = ""
    ) -> dict[str, Any]:
        work = self._work(scene_index)
        candidate_id = candidate_id.strip()
        if candidate_id not in work.candidate_ids:
            raise ImageToolError(
                "That candidate wasn't found by a search for this scene.", "not_found"
            )
        assessment = work.assessments.get(candidate_id)
        if assessment is None:
            raise ImageToolError(
                "Inspect it with inspect_image_candidates before downloading.", "not_assessed"
            )
        if assessment.decision != "accept":
            raise ImageToolError(
                f"Not accepted ({assessment.decision}): {' '.join(assessment.reasons)} "
                "It stays available to the user as an alternative.",
                "not_accepted",
            )
        if len(work.download_failures) >= MAX_DOWNLOAD_ATTEMPTS_PER_SCENE:
            raise ImageToolError("Too many failed downloads for this scene.", "budget_exhausted")
        candidate = self.candidate(candidate_id)
        try:
            image = self._fetch(candidate)
        except ImageToolError as exc:
            work.download_failures.append(f"{candidate_id}: {exc}")
            raise
        image_hash = difference_hash(image.data)
        duplicate = self._duplicate_of(scene_index, image_hash, None)
        if duplicate is not None:
            assessment.decision = "reject"
            assessment.reasons.append(f"Same image as scene {duplicate + 1}.")
            raise ImageToolError(
                f"This is the same image as scene {duplicate + 1}. Pick a different one.",
                "duplicate",
            )
        saved = self.download(
            candidate_id,
            scene_index,
            reason,
            metadata={
                "assessment": assessment.model_dump(),
                "brief_subject": work.brief.subject,
                "specificity": work.brief.specificity,
            },
        )
        duplicate = self._duplicate_of(scene_index, image_hash, saved["asset_id"])
        if duplicate is not None:
            raise ImageToolError(
                f"This is the same file as scene {duplicate + 1}. Pick a different one.",
                "duplicate",
            )
        self.used_assets[saved["asset_id"]] = scene_index
        self.used_hashes[scene_index] = image_hash
        verified = (
            "visually checked" if assessment.verification == "vision" else "visually unverified"
        )
        work.selected = SceneAsset(
            scene_index=scene_index,
            asset_id=saved["asset_id"],
            candidate_id=candidate_id,
            reason=(reason.strip() or "; ".join(assessment.reasons[:2]))[:300] + f" ({verified})",
            selected_by="visual",
            verification=assessment.verification,
            rights_status=candidate.rights_status,
        )
        work.gap = None
        return {**saved, "verification": assessment.verification}

    def report_gap(self, scene_index: int, missing: str, reason: str = "") -> dict[str, Any]:
        work = self._work(scene_index)
        work.gap = SceneGap(
            scene_index=scene_index,
            reason=(reason.strip() or self._gap_reason(work))[:400],
            missing=missing.strip()[:300] or self._missing(work.brief),
            actions=self._actions(work),
        )
        return work.gap.model_dump()

    # -- deterministic staged selection -----------------------------------

    def staged_select(self, scene_index: int) -> SceneAsset | None:
        """Search → filter → inspect → rank → download, only ever choosing accepted images."""
        work = self._work(scene_index)
        for planned in work.brief.queries:
            if work.selected is not None or len(work.searches) >= MAX_SEARCHES_PER_SCENE:
                break
            if query_problem(planned.query, work.brief):
                continue
            check_cancelled()
            try:
                self.scene_search(scene_index, planned.query, "auto", 10, planned.rationale)
            except ImageToolError:
                continue
            pending = [
                self.candidates[cid]
                for cid in work.candidate_ids
                if cid not in work.assessments
                and not technical_problems(self.candidates[cid], work.brief)
            ]
            pending.sort(key=lambda c: self._metadata_rank(c, work.brief), reverse=True)
            if pending and len(work.assessments) < MAX_INSPECTED_PER_SCENE:
                try:
                    self.scene_inspect(
                        scene_index, [c.candidate_id for c in pending[:MAX_INSPECT_BATCH]]
                    )
                except ImageToolError:
                    pass
            self._download_best(scene_index, work)
        if work.selected is None and work.gap is None:
            self.report_gap(scene_index, "")
        return work.selected

    def _metadata_rank(self, candidate: ImageCandidate, brief: VisualBrief) -> tuple[int, int, int]:
        signals = metadata_signals(candidate, brief)
        return (
            len(signals.entity_hits),
            len(signals.anchor_hits),
            1 if candidate.rights_status == "documented" else 0,
        )

    def _download_best(self, scene_index: int, work: SceneWork) -> None:
        for assessment in self._ranked(work):
            if work.selected is not None or assessment.decision != "accept":
                return
            if len(work.download_failures) >= MAX_DOWNLOAD_ATTEMPTS_PER_SCENE:
                return
            try:
                self.scene_download(scene_index, assessment.candidate_id)
            except ImageToolError:
                continue  # failures and duplicates are recorded on the scene

    # -- results ------------------------------------------------------------

    def _missing(self, brief: VisualBrief) -> str:
        if brief.requires_exact and brief.named_entities:
            names = ", ".join(entity.name for entity in brief.named_entities)
            return f"An image that verifiably shows {names} ({brief.subject})."
        return f"An image that clearly shows {brief.subject}."

    def _gap_reason(self, work: SceneWork) -> str:
        if not work.searches:
            return "No search was run for this scene."
        sources_tried = sorted({s["source"] for s in work.searches})
        checked = len(work.assessments)
        found = len(work.candidate_ids)
        if work.download_failures and any(
            a.decision == "accept" for a in work.assessments.values()
        ):
            return (
                "Suitable images were found but could not be downloaded: "
                + work.download_failures[-1]
            )
        if not found:
            return f"No results from {', '.join(sources_tried)} for the scene's subject."
        rejected = [a for a in work.assessments.values() if a.decision == "reject"]
        common = rejected[0].reasons[-1] if rejected and rejected[0].reasons else ""
        text = (
            f"{found} result(s) from {', '.join(sources_tried)}; {checked} checked against the "
            "brief and none was accepted automatically."
        )
        return f"{text} Typical problem: {common}" if common else text

    def _actions(self, work: SceneWork) -> list[GapAction]:
        actions: list[GapAction] = ["search_other_source", "refine_brief", "upload", "paste_url"]
        if any(a.decision in ("review", "illustrative") for a in work.assessments.values()):
            actions.append("choose_illustrative")
        actions.append("title_card")
        return actions

    def _alternatives(self, work: SceneWork) -> list[dict[str, Any]]:
        chosen = work.selected.candidate_id if work.selected else None
        items = []
        for assessment in self._ranked(work):
            if assessment.decision == "reject" or assessment.candidate_id == chosen:
                continue
            candidate = self.candidates[assessment.candidate_id]
            items.append(
                {
                    **candidate.public(),
                    "assessment": assessment.model_dump(),
                    "candidate": candidate.model_dump(),
                }
            )
            if len(items) >= MAX_ALTERNATIVES:
                break
        return items

    def scene_visual(self, scene_index: int) -> SceneVisual:
        work = self.work[scene_index]
        alternatives = self._alternatives(work)
        selected_assessment = (
            work.assessments.get(work.selected.candidate_id) if work.selected else None
        )
        if work.selected is not None:
            status = "selected"
        elif work.download_failures and any(
            a.decision == "accept" for a in work.assessments.values()
        ):
            status = "download_failed"
        elif alternatives:
            status = "awaiting_review"
        elif work.candidate_ids and not work.assessments:
            status = "candidates_found"
        else:
            status = "no_suitable_result"
        return SceneVisual(
            scene_index=scene_index,
            status=status,  # type: ignore[arg-type]
            brief=work.brief.summary(),
            searches=work.searches,
            alternatives=alternatives,
            assessment=selected_assessment.model_dump() if selected_assessment else None,
            note=work.gap.reason if work.gap and work.selected is None else "",
        )

    # -- model-facing tools -------------------------------------------------

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

        def build_visual_brief(
            scene_index: int,
            subject: str = "",
            specificity: str = "",
            named_entities: str = "",
            visual_type: str = "",
            excluded: str = "",
            queries: str = "",
        ) -> str:
            """Show a scene's visual brief, or tighten it. Refinements can't drop the subject.

            Args:
                scene_index: Zero-based scene index.
                subject: Optional sharper subject that keeps the original key words.
                specificity: Optional exact, representative or generic (can't be loosened when a
                    specific subject is named).
                named_entities: Optional extra names to require, "Name:kind; Name:kind".
                visual_type: Optional photograph, illustration, diagram, screenshot or background.
                excluded: Optional comma-separated concepts that must not appear.
                queries: Optional replacement search queries separated by "|", at most 4, each
                    keeping the subject.
            """
            args = {"scene_index": scene_index}
            if not any((subject, specificity, named_entities, visual_type, excluded, queries)):
                return toolkit._run(
                    "build_visual_brief",
                    args,
                    f"Reading the brief for scene {scene_index + 1}",
                    lambda: toolkit.brief(scene_index),
                )
            return toolkit._run(
                "build_visual_brief",
                {**args, "refined": True},
                f"Refining the brief for scene {scene_index + 1}",
                lambda: toolkit.refine_brief(
                    scene_index,
                    subject=subject,
                    specificity=specificity,
                    named_entities=named_entities,
                    visual_type=visual_type,
                    excluded=excluded,
                    queries=queries,
                ),
            )

        def search_image_sources(
            scene_index: int, query: str, source: str = "auto", limit: int = 8, rationale: str = ""
        ) -> str:
            """Search image sources for one scene. Queries must keep the scene's subject.

            Args:
                scene_index: Zero-based scene index.
                query: Search phrase that keeps the subject (and full names for exact subjects).
                    For source "url" or "webpage" pass the exact URL the user supplied.
                source: auto (licensed sources chosen for the brief), pexels, pixabay, wikimedia
                    (best for named places, people, species, artworks and diagrams), openverse,
                    brave (web discovery with unknown rights, once per scene, only after the
                    licensed sources failed), url or webpage.
                limit: Maximum candidates, 1 to 12.
                rationale: One short sentence on why this query and source.
            """
            args = {"scene_index": scene_index, "query": query, "source": source, "limit": limit}
            return toolkit._run(
                "search_image_sources",
                args,
                f"Searching {source} for scene {scene_index + 1}: “{query[:60]}”",
                lambda: toolkit.scene_search(scene_index, query, source, limit, rationale),
            )

        def inspect_image_candidates(scene_index: int, candidate_ids: str) -> str:
            """Check candidates' previews against the brief (vision when available).

            Args:
                scene_index: Zero-based scene index.
                candidate_ids: Comma-separated candidate IDs from search_image_sources, at most 6.
            """
            ids = [item for item in candidate_ids.split(",") if item.strip()]
            return toolkit._run(
                "inspect_image_candidates",
                {"scene_index": scene_index, "candidate_ids": ids},
                f"Checking {len(ids)} image(s) for scene {scene_index + 1}",
                lambda: toolkit.scene_inspect(scene_index, ids),
            )

        def rank_image_candidates(scene_index: int) -> str:
            """Rank the inspected candidates for a scene into accepted, review and illustrative.

            Args:
                scene_index: Zero-based scene index.
            """
            return toolkit._run(
                "rank_image_candidates",
                {"scene_index": scene_index},
                f"Ranking images for scene {scene_index + 1}",
                lambda: toolkit.scene_rank(scene_index),
            )

        def download_and_register_image(
            scene_index: int, candidate_id: str, reason: str = ""
        ) -> str:
            """Download an accepted candidate, validate it and assign it to the scene.

            Args:
                scene_index: Zero-based scene index.
                candidate_id: A candidate whose assessment is "accept".
                reason: One short sentence on why it fits the scene.
            """
            return toolkit._run(
                "download_and_register_image",
                {"scene_index": scene_index, "candidate_id": candidate_id},
                f"Downloading an image for scene {scene_index + 1}",
                lambda: toolkit.scene_download(scene_index, candidate_id, reason),
            )

        def list_project_assets() -> str:
            """List images already in this project and which scene uses each."""
            return toolkit._run(
                "list_project_assets", {}, "Listing project images", toolkit.list_assets
            )

        def report_visual_gap(scene_index: int, missing: str, reason: str = "") -> str:
            """Record that no suitable image was found, so the scene stays honestly unresolved.

            Args:
                scene_index: Zero-based scene index.
                missing: What a suitable image would have to show.
                reason: What was tried and why nothing qualified.
            """
            return toolkit._run(
                "report_visual_gap",
                {"scene_index": scene_index},
                f"Reporting that scene {scene_index + 1} has no suitable image",
                lambda: toolkit.report_gap(scene_index, missing, reason),
            )

        return [
            build_visual_brief,
            search_image_sources,
            inspect_image_candidates,
            rank_image_candidates,
            download_and_register_image,
            list_project_assets,
            report_visual_gap,
        ]
