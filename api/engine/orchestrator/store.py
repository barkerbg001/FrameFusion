"""Persistence interface the orchestrator uses.

The engine never imports Django. The studio app implements ``ProjectStore``
on top of SQLite (``studio/store.py``) and installs it for the duration of a job.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from engine.orchestrator.schemas import TaskRecord, TaskStatus

if TYPE_CHECKING:
    from engine.services.images.candidates import ImageCandidate, ValidatedImage


class ProjectStore(Protocol):
    project_id: str
    job_id: str | None

    # Assets ---------------------------------------------------------------
    def save_image(
        self, image: ValidatedImage, candidate: ImageCandidate, *, scene_index: int | None
    ) -> dict[str, Any]: ...

    def list_assets(self, kind: str | None = None) -> list[dict[str, Any]]: ...

    def asset(self, asset_id: str) -> dict[str, Any] | None: ...

    def asset_path(self, asset_id: str) -> Path | None: ...

    def new_output_path(self, stem: str, suffix: str) -> Path: ...

    def register_output(
        self,
        path: Path,
        *,
        role: str,
        duration_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    # Tasks ----------------------------------------------------------------
    def latest_task(self, stage: str) -> TaskRecord | None: ...

    def tasks(self) -> list[TaskRecord]: ...

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
        status: TaskStatus = "proposed",
    ) -> TaskRecord: ...

    def update_task(self, task_id: str, **fields: Any) -> TaskRecord: ...

    def invalidate(self, stages: list[str], reason: str) -> None: ...

    def run_in_thread(self, fn: Callable[[], Any]) -> Future[Any]: ...
