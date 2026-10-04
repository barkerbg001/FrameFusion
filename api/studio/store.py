"""SQLite implementation of ``engine.orchestrator.store.ProjectStore``."""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.utils import timezone

from engine import paths
from engine.orchestrator.schemas import TaskRecord
from engine.services.images.candidates import ImageCandidate, ValidatedImage, safe_slug

from . import media
from .models import GenerationJob, MediaAsset, ProductionTask, Project

_side_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="framefusion-side")

TASK_FIELDS = {
    "status",
    "attempt",
    "output",
    "artifact_ids",
    "error",
    "limitations",
    "input_hash",
    "inputs",
    "job_id",
}


def task_record(task: ProductionTask) -> TaskRecord:
    return TaskRecord(
        id=str(task.pk),
        project_id=str(task.project_id),
        job_id=str(task.job_id) if task.job_id else None,
        stage=task.stage,
        specialist=task.specialist,
        objective=task.objective,
        inputs=task.inputs or {},
        depends_on=list(task.depends_on or []),
        expected_output=task.expected_output,
        status=task.status,  # type: ignore[arg-type]
        attempt=task.attempt,
        max_attempts=task.max_attempts,
        input_hash=task.input_hash,
        output=task.output,
        artifact_ids=list(task.artifact_ids or []),
        error=task.error,
        limitations=list(task.limitations or []),
    )


def asset_record(asset: MediaAsset) -> dict[str, Any]:
    path = media.generated_file(asset.file_name)
    return {
        **media.asset_payload(asset),
        "name": asset.display_name,
        "exists": path is not None,
        "provider": asset.provider or None,
        "license": asset.license or "unknown",
        "rights_status": asset.rights_status or "unknown",
        "candidate_id": asset.candidate_id,
        "width": asset.width,
        "height": asset.height,
        "scene_index": (asset.metadata or {}).get("scene_index"),
        "user_supplied": asset.user_supplied,
        "dhash": (asset.metadata or {}).get("dhash"),
    }


class DjangoProjectStore:
    def __init__(self, project: Project, job: GenerationJob | None = None) -> None:
        self.project = project
        self.job = job
        self.project_id = str(project.pk)
        self.job_id = str(job.pk) if job else None

    # -- assets ---------------------------------------------------------

    def save_image(
        self,
        image: ValidatedImage,
        candidate: ImageCandidate,
        *,
        scene_index: int | None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = MediaAsset.objects.filter(project=self.project, checksum=image.sha256).first()
        if existing is not None and media.generated_file(existing.file_name):
            return {**asset_record(existing), "reused": True}
        directory = media.project_dir(self.project_id)
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{image.sha256[:16]}-{safe_slug(candidate.title, 'image', 40)}"
        file_name = f"projects/{self.project_id}/{stem}.{image.extension}"
        final = directory / f"{stem}.{image.extension}"
        handle, temp_name = tempfile.mkstemp(dir=directory, suffix=".part")
        try:
            with os.fdopen(handle, "wb") as out:
                out.write(image.data)
            os.replace(temp_name, final)
        finally:
            Path(temp_name).unlink(missing_ok=True)
        fields = {
            "project": self.project,
            "job": self.job,
            "kind": MediaAsset.Kind.IMAGE,
            "role": "scene_image",
            "display_name": f"{safe_slug(candidate.title, 'image', 60)}.{image.extension}",
            "size_bytes": image.size_bytes,
            "provider": candidate.provider,
            "candidate_id": candidate.candidate_id[:120],
            "source_url": candidate.download_url[:2048],
            "source_page_url": (candidate.source_page_url or "")[:2048],
            "title": candidate.title[:200],
            "creator": (candidate.creator or "")[:200],
            "creator_url": (candidate.creator_url or "")[:2048],
            "license": candidate.license[:80],
            "license_url": (candidate.license_url or "")[:2048],
            "attribution": (candidate.attribution or "")[:500],
            "rights_status": candidate.rights_status,
            "user_supplied": candidate.user_supplied,
            "checksum": image.sha256,
            "mime": image.mime,
            "width": image.width,
            "height": image.height,
            "metadata": {
                **(metadata or {}),
                "scene_index": scene_index,
                "usage_note": candidate.usage_note[:400],
                **{
                    key: value
                    for key, value in (
                        ("discovered_via", candidate.discovered_via),
                        ("publisher", (candidate.publisher or "")[:200] or None),
                        ("found_on_page", candidate.found_on_page),
                    )
                    if value is not None
                },
            },
        }
        try:
            with transaction.atomic():
                asset = MediaAsset.objects.create(file_name=file_name, **fields)
        except IntegrityError:
            asset = MediaAsset.objects.filter(
                project=self.project, checksum=image.sha256
            ).first() or (MediaAsset.objects.get(file_name=file_name))
            return {**asset_record(asset), "reused": True}
        return {**asset_record(asset), "reused": False}

    def list_assets(self, kind: str | None = None) -> list[dict[str, Any]]:
        queryset = MediaAsset.objects.filter(project=self.project)
        if kind:
            queryset = queryset.filter(kind=kind)
        return [asset_record(asset) for asset in queryset.order_by("created_at")]

    def _asset(self, asset_id: str) -> MediaAsset | None:
        try:
            key = uuid.UUID(str(asset_id))
        except ValueError:
            return None
        return MediaAsset.objects.filter(pk=key, project=self.project).first()

    def asset(self, asset_id: str) -> dict[str, Any] | None:
        asset = self._asset(asset_id)
        return asset_record(asset) if asset else None

    def asset_path(self, asset_id: str) -> Path | None:
        asset = self._asset(asset_id)
        return media.generated_file(asset.file_name) if asset else None

    def new_output_path(self, stem: str, suffix: str) -> Path:
        directory = paths.GENERATED_DIR
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{uuid.uuid4().hex}_{safe_slug(stem, 'output', 60)}{suffix}"

    def register_output(
        self,
        path: Path,
        *,
        role: str,
        duration_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        asset = media.register_asset(
            path.name, project=self.project, job=self.job, duration_seconds=duration_seconds
        )
        if asset is None:
            raise FileNotFoundError(f"{path.name} was not written to the output folder.")
        asset.role = role
        asset.metadata = metadata or {}
        if duration_seconds is not None:
            asset.duration_seconds = duration_seconds
        asset.size_bytes = path.stat().st_size
        asset.save(update_fields=["role", "metadata", "duration_seconds", "size_bytes"])
        return asset_record(asset)

    # -- tasks ----------------------------------------------------------

    def latest_task(self, stage: str) -> TaskRecord | None:
        task = (
            ProductionTask.objects.filter(project=self.project, stage=stage)
            .order_by("-created_at", "-updated_at")
            .first()
        )
        return task_record(task) if task else None

    def tasks(self) -> list[TaskRecord]:
        return [task_record(task) for task in ProductionTask.objects.filter(project=self.project)]

    def create_task(
        self,
        *,
        stage: str,
        specialist: str,
        objective: str,
        inputs: dict[str, Any],
        depends_on: list[str],
        input_hash: str,
        max_attempts: int,
        status: str = "proposed",
    ) -> TaskRecord:
        task = ProductionTask.objects.create(
            project=self.project,
            job=self.job,
            stage=stage,
            specialist=specialist,
            objective=objective[:600],
            inputs=inputs,
            depends_on=depends_on,
            input_hash=input_hash,
            max_attempts=max_attempts,
            status=status,
        )
        return task_record(task)

    def update_task(self, task_id: str, **fields: Any) -> TaskRecord:
        unknown = set(fields) - TASK_FIELDS
        if unknown:
            raise ValueError(f"Unknown task fields: {', '.join(sorted(unknown))}")
        if fields.get("status") == ProductionTask.Status.ACTIVE:
            task = ProductionTask.objects.get(pk=task_id)
            # A task left active by a crashed run must not block this one.
            ProductionTask.objects.filter(
                project=self.project, stage=task.stage, status=ProductionTask.Status.ACTIVE
            ).exclude(pk=task_id).update(
                status=ProductionTask.Status.FAILED,
                error={"kind": "interrupted", "message": "Interrupted before it finished."},
                updated_at=timezone.now(),
            )
            fields.setdefault("job_id", self.job.pk if self.job else None)
        ProductionTask.objects.filter(pk=task_id).update(**fields, updated_at=timezone.now())
        return task_record(ProductionTask.objects.get(pk=task_id))

    def invalidate(self, stages: list[str], reason: str) -> None:
        for stage in stages:
            latest = (
                ProductionTask.objects.filter(project=self.project, stage=stage)
                .order_by("-created_at")
                .first()
            )
            if latest is not None and latest.status == ProductionTask.Status.VERIFIED:
                ProductionTask.objects.filter(pk=latest.pk).update(
                    status=ProductionTask.Status.INVALIDATED,
                    error={"kind": "invalidated", "message": reason},
                    updated_at=timezone.now(),
                )

    def run_in_thread(self, fn: Callable[[], Any]) -> Future[Any]:
        if settings.FRAMEFUSION_JOBS_EAGER:
            future: Future[Any] = Future()
            try:
                future.set_result(fn())
            except BaseException as exc:  # noqa: BLE001 - surfaced through the future
                future.set_exception(exc)
            return future

        def wrapped() -> Any:
            close_old_connections()
            try:
                return fn()
            finally:
                connection.close()

        return _side_pool.submit(wrapped)


def replace_scene_asset(
    project: Project,
    scene_index: int,
    asset: MediaAsset | None,
    *,
    illustrative: bool = False,
    title_card: bool = False,
) -> dict[str, Any]:
    """Point a scene at a different image (or none, or a title card); invalidate the render.

    Only the render and QC depend on scene images, so narration and other scenes are reused.
    """
    from engine.orchestrator.schemas import (
        SceneAsset,
        SceneGap,
        SceneVisual,
        VisualResult,
        downstream_of,
    )

    store = DjangoProjectStore(project)
    task = store.latest_task("visuals")
    script_task = store.latest_task("script")
    if task is None or task.output is None or script_task is None or not script_task.output:
        raise ValueError("This project has no planned scenes yet. Run a production first.")
    scenes = script_task.output.get("scenes") or []
    if not 0 <= scene_index < len(scenes):
        raise ValueError(f"Scene must be between 1 and {len(scenes)}.")
    result = VisualResult.model_validate(task.output)
    assets = [item for item in result.scene_assets if item.scene_index != scene_index]
    gaps = [gap for gap in result.gaps if gap.scene_index != scene_index]
    state = result.scene_state(scene_index) or SceneVisual(scene_index=scene_index)
    if asset is not None:
        label = "Chosen by you as an illustration" if illustrative else "Chosen by you"
        assets.append(
            SceneAsset(
                scene_index=scene_index,
                asset_id=str(asset.pk),
                candidate_id=asset.candidate_id,
                reason=label,
                selected_by="user",
                verification="user",
                rights_status="documented" if asset.rights_status == "documented" else "unknown",
                illustrative=illustrative,
            )
        )
        state.status = "selected"
        state.note = ""
        state.alternatives = [
            item for item in state.alternatives if item.get("candidate_id") != asset.candidate_id
        ]
    elif title_card:
        gaps.append(
            SceneGap(
                scene_index=scene_index,
                reason="Title card chosen by you.",
                actions=["upload", "paste_url"],
            )
        )
        state.status = "title_card"
        state.note = "Title card chosen by you."
    else:
        gaps.append(
            SceneGap(
                scene_index=scene_index,
                reason="Removed by you",
                actions=["search_other_source", "upload", "paste_url", "title_card"],
            )
        )
        state.status = "awaiting_review" if state.alternatives else "no_suitable_result"
        state.note = "Removed by you."
    result.scenes = sorted(
        [item for item in result.scenes if item.scene_index != scene_index] + [state],
        key=lambda item: item.scene_index,
    )
    result.scene_assets = sorted(assets, key=lambda item: item.scene_index)
    result.gaps = sorted(gaps, key=lambda item: item.scene_index)
    ProductionTask.objects.filter(pk=task.id).update(
        output=result.model_dump(),
        artifact_ids=[item.asset_id for item in result.scene_assets],
        updated_at=timezone.now(),
    )
    store.invalidate(downstream_of("visuals"), reason="A scene image changed")
    return result.model_dump()


def detach_asset(asset: MediaAsset) -> None:
    """Remove a deleted image from any scene that used it."""
    if asset.project is None or asset.kind != MediaAsset.Kind.IMAGE:
        return
    store = DjangoProjectStore(asset.project)
    task = store.latest_task("visuals")
    if task is None or not task.output:
        return
    for item in task.output.get("scene_assets") or []:
        if item.get("asset_id") == str(asset.pk):
            replace_scene_asset(asset.project, int(item["scene_index"]), None)
