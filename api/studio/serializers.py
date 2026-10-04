"""JSON shapes returned by the studio API."""

from __future__ import annotations

from typing import Any

from engine.orchestrator.personalities import get_personality
from engine.orchestrator.schemas import STAGE_LABELS, STAGES

from .models import GenerationJob, JobEvent, Message, ProductionTask, Project


def iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def project_stage(project: Project) -> str | None:
    """Derived from recorded work only; None when the list annotations are absent."""
    if not hasattr(project, "latest_job_status"):
        return None
    status = getattr(project, "latest_job_status", None)
    if status in GenerationJob.ACTIVE:
        return "in_production"
    if status == GenerationJob.Status.FAILED:
        return "needs_attention"
    if getattr(project, "video_count", 0):
        return "delivered"
    if getattr(project, "message_count", 0):
        return "developing"
    return "idea"


def default_personality() -> str:
    from providers.models import AppSettings

    return get_personality(AppSettings.load().orchestrator_personality).id


def effective_personality(project: Project | None, default: str | None = None) -> str:
    chosen = project.personality if project else ""
    return get_personality(chosen or default or default_personality()).id


def project_payload(project: Project, *, default: str | None = None) -> dict[str, Any]:
    return {
        "id": str(project.pk),
        "title": project.title,
        "title_locked": project.title_locked,
        "personality": project.personality or None,
        "effective_personality": effective_personality(project, default),
        "narration": {
            "provider": project.narration_provider or None,
            "voice": project.narration_voice,
            "voice_label": project.narration_voice_label,
        },
        "created_at": iso(project.created_at),
        "updated_at": iso(project.updated_at),
        "message_count": getattr(project, "message_count", None),
        "media_count": getattr(project, "media_count", None),
        "last_message": getattr(project, "last_message", None),
        "video_count": getattr(project, "video_count", None),
        "stage": project_stage(project),
    }


def message_payload(message: Message) -> dict[str, Any]:
    return {
        "id": message.pk,
        "role": message.role,
        "content": message.content,
        "persona": message.persona or None,
        "attachments": message.attachments or [],
        "job_id": str(message.job_id) if message.job_id else None,
        "created_at": iso(message.created_at),
    }


def event_payload(event: JobEvent) -> dict[str, Any]:
    return {
        "seq": event.seq,
        "type": event.type,
        "agent": event.agent or None,
        "persona": event.persona or None,
        "message": event.message,
        "data": event.data,
        "created_at": iso(event.created_at),
    }


def task_payload(task: ProductionTask) -> dict[str, Any]:
    return {
        "id": str(task.pk),
        "stage": task.stage,
        "label": STAGE_LABELS.get(task.stage, task.stage),
        "specialist": task.specialist,
        "status": task.status,
        "attempt": task.attempt,
        "max_attempts": task.max_attempts,
        "artifact_ids": task.artifact_ids or [],
        "limitations": task.limitations or [],
        "error": {k: v for k, v in (task.error or {}).items() if k in ("kind", "message")} or None,
        "job_id": str(task.job_id) if task.job_id else None,
        "updated_at": iso(task.updated_at),
    }


def production_state(project: Project) -> dict[str, Any]:
    """The latest task per stage plus the scene list and scene-to-image map."""
    latest: dict[str, ProductionTask] = {}
    for task in ProductionTask.objects.filter(project=project).order_by("created_at"):
        latest[task.stage] = task
    script = latest.get("script")
    visuals = latest.get("visuals")
    scenes = (script.output or {}).get("scenes", []) if script and script.output else []
    visual_output = (visuals.output or {}) if visuals and visuals.output else {}
    by_scene = {item["scene_index"]: item for item in visual_output.get("scene_assets", []) or []}
    gaps = {gap["scene_index"]: gap["reason"] for gap in visual_output.get("gaps", []) or []}
    return {
        "tasks": [task_payload(latest[stage]) for stage in STAGES if stage in latest],
        "scenes": [
            {
                "index": scene.get("index", position),
                "narration": scene.get("narration", ""),
                "on_screen_text": scene.get("on_screen_text", ""),
                "visual_description": scene.get("visual_description", ""),
                "image_query": scene.get("image_query", ""),
                "asset_id": (by_scene.get(position) or {}).get("asset_id"),
                "selected_by": (by_scene.get(position) or {}).get("selected_by"),
                "reason": (by_scene.get(position) or {}).get("reason"),
                "gap": gaps.get(position),
            }
            for position, scene in enumerate(scenes)
        ],
        "brief": (latest["brief"].output if "brief" in latest else None),
    }


def public_error(error: dict[str, Any] | None) -> dict[str, Any] | None:
    """The narration render spec holds local file paths; the browser only needs a flag."""
    if not error:
        return error
    public = {k: v for k, v in error.items() if k != "render_spec"}
    if error.get("render_spec"):
        public["can_retry_narration"] = True
    return public


def job_payload(
    job: GenerationJob, *, events_after: int | None = None, include_result: bool = True
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(job.pk),
        "kind": job.kind,
        "agent": job.agent or None,
        "status": job.status,
        "project_id": str(job.project_id) if job.project_id else None,
        "input": job.input,
        "error": public_error(job.error),
        "usage": job.usage or [],
        "cancel_requested": job.cancel_requested,
        "retry_of": str(job.retry_of_id) if job.retry_of_id else None,
        "created_at": iso(job.created_at),
        "started_at": iso(job.started_at),
        "finished_at": iso(job.finished_at),
    }
    if include_result:
        payload["result"] = job.result
    if events_after is not None:
        events = job.events.filter(seq__gt=events_after).order_by("seq")
        payload["events"] = [event_payload(event) for event in events]
    return payload
