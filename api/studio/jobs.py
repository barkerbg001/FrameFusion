"""In-process background jobs backed by SQLite.

Long-running agent work (chat replies, production pipelines, renders) runs on a
small thread pool inside the Django process. Every job and its progress events
are rows in SQLite, so the UI polls ``/api/jobs/<id>`` and never holds an HTTP
request open while a model or renderer works.

This runner assumes a single server process (``manage.py runserver`` or one
worker of a WSGI server). Jobs left queued/running by a previous process are
marked as interrupted the first time this process touches the queue.
"""

from __future__ import annotations

import contextvars
import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from django.conf import settings
from django.db import close_old_connections, connection
from django.db.models import F
from django.utils import timezone

from common.http import find_llm_error
from engine.integrations import IntegrationNotConfigured
from engine.llm import LLMError, use_llm_resolver
from engine.orchestrator.personalities import get_personality
from engine.orchestrator.production import ProductionStageError
from engine.orchestrator.schemas import STAGE_LABELS
from engine.runtime import RunCancelled, run_context
from engine.services.narration import (
    NarrationError,
    NarrationStageError,
    find_narration_error,
    project_override,
)
from providers.clients import redact
from providers.services import make_resolver

from .models import GenerationJob, JobEvent, ProductionTask

logger = logging.getLogger(__name__)

BOOT_ID = uuid.uuid4().hex
BOOT_TIME = timezone.now()
MAX_EVENTS_PER_JOB = 400

SPECIALIST_NAMES: dict[str, str] = {
    "research": "Research specialist",
    "script": "Script specialist",
    "visual": "Visual specialist",
    "ideas": "Ideas specialist",
    "music_composer": "Music specialist",
    "narration": "Narration",
    "music": "Music bed",
    "renderer": "Renderer",
    "qc": "Quality check",
}
AGENT_TASKS: dict[str, str] = {
    "orchestrator": "thinking it through",
    "research": "researching the topic",
    "script": "writing the script",
    "ideas": "brainstorming ideas",
    "visual": "finding images",
    "music_composer": "composing the score",
}
STEP_STATUS_WORDS: dict[str, str] = {
    "running": "started",
    "reused": "reused (inputs unchanged)",
    "done": "verified",
    "failed": "failed",
    "cancelled": "cancelled",
}
LEGACY_AGENTS = {"framey": "orchestrator", "director": "orchestrator", "voice": "narration"}

Handler = Callable[[GenerationJob], dict[str, Any]]
HANDLERS: dict[str, Handler] = {}

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()
_recovered = False


def register(kind: str) -> Callable[[Handler], Handler]:
    def decorator(handler: Handler) -> Handler:
        HANDLERS[kind] = handler
        return handler

    return decorator


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=settings.FRAMEFUSION_JOB_WORKERS, thread_name_prefix="framefusion-job"
            )
        return _executor


def job_personality(job: GenerationJob) -> str:
    """The personality snapshotted when the job was created.

    Switching personality mid-run never changes a running job; the new voice applies
    from the next job (the next safe turn boundary).
    """
    return get_personality(str((job.input or {}).get("personality") or "")).id


def recover_interrupted_jobs() -> int:
    global _recovered
    if _recovered:
        return 0
    _recovered = True
    stale = GenerationJob.objects.filter(
        status__in=GenerationJob.ACTIVE, created_at__lt=BOOT_TIME
    ).exclude(boot_id=BOOT_ID)
    ProductionTask.objects.filter(status=ProductionTask.Status.ACTIVE, job__in=stale).update(
        status=ProductionTask.Status.FAILED,
        error={"kind": "interrupted", "message": "The server restarted during this task."},
        updated_at=timezone.now(),
    )
    return stale.update(
        status=GenerationJob.Status.FAILED,
        error={
            "kind": "interrupted",
            "message": "The server restarted before this job finished. Retry to run it again.",
        },
        finished_at=timezone.now(),
    )


def submit(job: GenerationJob) -> GenerationJob:
    """Queue a saved job. Call outside of an open transaction."""
    import studio.handlers  # noqa: F401  (registers job handlers)
    import tools.handlers  # noqa: F401

    recover_interrupted_jobs()
    GenerationJob.objects.filter(pk=job.pk).update(boot_id=BOOT_ID)
    if settings.FRAMEFUSION_JOBS_EAGER:
        execute(job.pk)
    else:
        context = contextvars.Context()
        _get_executor().submit(context.run, _execute_in_thread, job.pk)
    job.refresh_from_db()
    return job


def _execute_in_thread(job_id: uuid.UUID) -> None:
    close_old_connections()
    try:
        execute(job_id)
    finally:
        connection.close()


class EventWriter:
    """Turns engine reports into job events.

    Orchestrator events carry the job's personality; specialist and service events
    carry the specialist ID only, so the UI never presents a specialist as a personality.
    Model reasoning is never recorded, only what an agent is doing and with which tool.
    """

    def __init__(self, job: GenerationJob) -> None:
        self.job_id = job.pk
        self.personality = job_personality(job)
        self.seq = JobEvent.objects.filter(job_id=job.pk).count()
        self.usage: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def _name(self, agent: str) -> str:
        if agent == "orchestrator":
            return get_personality(self.personality).name
        return SPECIALIST_NAMES.get(agent, agent.replace("_", " ").capitalize() or "Agent")

    def emit(
        self,
        type_: str,
        message: str = "",
        *,
        agent: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        with self.lock:
            if self.seq >= MAX_EVENTS_PER_JOB:
                return
            self.seq += 1
            agent = LEGACY_AGENTS.get(agent, agent)
            persona = self.personality if agent == "orchestrator" else ""
            JobEvent.objects.create(
                job_id=self.job_id,
                seq=self.seq,
                type=type_,
                agent=agent,
                persona=persona,
                message=redact(message)[:500],
                data=data or {},
            )

    def __call__(self, event: str, data: dict[str, Any]) -> None:
        agent = str(data.get("agent") or "")
        if event == "usage":
            key = f"{data.get('provider')}:{data.get('model')}"
            entry = self.usage.setdefault(
                key,
                {
                    "provider": data.get("provider"),
                    "model": data.get("model"),
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                },
            )
            entry["calls"] += 1
            entry["input_tokens"] += data.get("input_tokens") or 0
            entry["output_tokens"] += data.get("output_tokens") or 0
            return
        if event == "llm_call":
            task = AGENT_TASKS.get(agent, agent.replace("_", " ") or "next step")
            self.emit(
                "thinking",
                f"{self._name(agent)} is {task} with {data.get('model')}",
                agent=agent,
                data={
                    "provider": data.get("provider"),
                    "model": data.get("model"),
                    "route": data.get("route"),
                },
            )
        elif event == "tool_start":
            tool = str(data.get("tool") or "tool")
            label = str(data.get("label") or f"Working on {tool.replace('_', ' ')}")
            self.emit(
                "tool",
                f"{label}…",
                agent=agent,
                data={"tool": tool, "status": "running"},
            )
        elif event == "tool":
            tool = str(data.get("tool") or "tool")
            ok = bool(data.get("ok"))
            self.emit(
                "tool",
                f"Used {tool.replace('_', ' ')}" if ok else f"{tool.replace('_', ' ')} failed",
                agent=agent,
                data={
                    "tool": tool,
                    "ok": ok,
                    "error": redact(str(data.get("error") or ""))[:300],
                },
            )
        elif event == "step":
            status = str(data.get("status") or "")
            stage = str(data.get("stage") or agent)
            label = STAGE_LABELS.get(stage, stage.replace("_", " ").capitalize())
            self.emit(
                "step",
                f"{label} {STEP_STATUS_WORDS.get(status, status)}",
                agent=agent,
                data={"status": status, "stage": stage, "task_id": data.get("task_id")},
            )
        else:
            self.emit(event, str(data.get("message") or ""), agent=agent, data={})


class _CancelCheck:
    def __init__(self, job_id: uuid.UUID) -> None:
        self.job_id = job_id
        self.last = 0.0

    def __call__(self) -> None:
        now = time.monotonic()
        if now - self.last < 1.5:
            return
        self.last = now
        if GenerationJob.objects.filter(pk=self.job_id, cancel_requested=True).exists():
            raise RunCancelled()


def _cancelled_in_chain(exc: BaseException | None) -> bool:
    depth = 0
    while exc is not None and depth < 10:
        if isinstance(exc, RunCancelled):
            return True
        exc = exc.__cause__ or exc.__context__
        depth += 1
    return False


def _find_in_chain[E: BaseException](exc: BaseException | None, kind: type[E]) -> E | None:
    depth = 0
    while exc is not None and depth < 12:
        if isinstance(exc, kind):
            return exc
        exc = exc.__cause__ or exc.__context__
        depth += 1
    return None


def _find_narration_stage(exc: BaseException | None) -> NarrationStageError | None:
    return _find_in_chain(exc, NarrationStageError)


def error_payload(exc: BaseException) -> dict[str, Any]:
    llm_error = find_llm_error(exc)
    if llm_error is not None:
        return llm_error.to_dict()
    narration_error = find_narration_error(exc)
    if narration_error is not None:
        stage = _find_narration_stage(exc)
        payload: dict[str, Any] = {
            "kind": "narration_failed",
            "message": redact(str(stage) if stage else narration_error.message),
            "provider": narration_error.provider,
            "retryable": narration_error.retryable,
            "settings_path": "#/settings/narration",
        }
        if stage is not None:
            payload["render_spec"] = stage.render_spec
        return payload
    if isinstance(exc, IntegrationNotConfigured):
        return {"kind": "not_configured", "message": str(exc), "service": exc.service}
    stage_error = _find_in_chain(exc, ProductionStageError)
    if stage_error is not None:
        return {**stage_error.to_dict(), "message": redact(stage_error.message)}
    if isinstance(exc, ValueError):
        return {"kind": "bad_request", "message": redact(str(exc))}
    message = redact(str(exc)) or "The job failed unexpectedly."
    return {"kind": "agent_error", "message": message}


def execute(job_id: uuid.UUID) -> None:
    job = GenerationJob.objects.get(pk=job_id)
    if job.status != GenerationJob.Status.QUEUED:
        return
    if job.cancel_requested:
        _finish(
            job,
            "cancelled",
            error={"kind": "cancelled", "message": "Cancelled."},
        )
        return

    updated = GenerationJob.objects.filter(pk=job.pk, status=GenerationJob.Status.QUEUED).update(
        status=GenerationJob.Status.RUNNING, started_at=timezone.now(), boot_id=BOOT_ID
    )
    if not updated:
        return
    job.refresh_from_db()

    writer = EventWriter(job)
    writer.emit("status", "Started", agent=job.agent, data={"status": "running"})
    handler = HANDLERS[job.kind]
    project = job.project
    try:
        resolver = make_resolver()
        with (
            use_llm_resolver(resolver),
            run_context(writer, _CancelCheck(job.pk)),
            project_override(
                project.narration_provider if project else "",
                project.narration_voice if project else "",
                project.narration_voice_label if project else "",
            ),
        ):
            result = handler(job)
    except BaseException as exc:  # noqa: BLE001 - record every failure on the job row
        job.refresh_from_db(fields=["cancel_requested"])
        if _cancelled_in_chain(exc) or job.cancel_requested:
            writer.emit("status", "Cancelled", data={"status": "cancelled"})
            _finish(
                job,
                "cancelled",
                error={"kind": "cancelled", "message": "Cancelled."},
                usage=writer.usage,
            )
            return
        payload = error_payload(exc)
        expected = (
            LLMError | ValueError | IntegrationNotConfigured | NarrationError | ProductionStageError
        )
        if (
            not isinstance(exc, expected)
            and find_llm_error(exc) is None
            and payload["kind"] != "narration_failed"
        ):
            logger.exception("Job %s failed", job.pk)
        writer.emit(
            "status", payload["message"], data={"status": "failed", "kind": payload["kind"]}
        )
        _finish(job, "failed", error=payload, usage=writer.usage)
        if not isinstance(exc, Exception):
            raise
        return

    writer.emit("status", "Finished", data={"status": "succeeded"})
    _finish(job, "succeeded", result=result, usage=writer.usage)


def _finish(
    job: GenerationJob,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
) -> None:
    GenerationJob.objects.filter(pk=job.pk).update(
        status=status,
        result=result,
        error=error,
        usage=list((usage or {}).values()) if usage else F("usage"),
        finished_at=timezone.now(),
    )
