"""Job handlers. Each runs inside a job's LLM resolver and run context."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.utils import timezone

from engine.orchestrator.chat import ChatTurn, run_orchestrator_chat
from engine.orchestrator.production import run_production
from engine.orchestrator.schemas import ProductionRequest
from engine.paths import GENERATED_DIR
from engine.runtime import report
from engine.services import narration

from .agent_specs import AGENT_SPECS, run_spec
from .jobs import job_personality, register
from .media import asset_payload, register_from_result
from .models import GenerationJob, MediaAsset, Message, Project
from .store import DjangoProjectStore

HISTORY_LIMIT = 50


def _touch(project: Project | None) -> None:
    if project is not None:
        Project.objects.filter(pk=project.pk).update(updated_at=timezone.now())


def _attachment(asset: MediaAsset, duration: float | None = None) -> dict[str, Any]:
    payload = asset_payload(asset)
    payload.update(
        type=asset.kind,
        filename=asset.display_name,
        duration_seconds=duration if duration is not None else asset.duration_seconds,
    )
    return payload


def _video_attachments(project: Project, result: dict[str, Any] | None) -> list[dict[str, Any]]:
    video = (result or {}).get("video") or {}
    if not video.get("id"):
        return []
    asset = MediaAsset.objects.filter(pk=video["id"], project=project).first()
    return [_attachment(asset)] if asset else []


@register("chat")
def handle_chat(job: GenerationJob) -> dict[str, Any]:
    project = job.project
    if project is None:
        raise ValueError("Chat jobs need a project.")
    history = project.messages.all()
    user_message_id = job.input.get("user_message_id")
    if user_message_id:
        history = history.filter(id__lte=user_message_id)
    recent = list(history.order_by("-created_at", "-id")[:HISTORY_LIMIT])[::-1]
    turns = [
        ChatTurn(
            role="assistant" if m.role == Message.Role.ASSISTANT else "user",
            content=m.content[:8000],
        )
        for m in recent
        if m.content.strip() and m.role in (Message.Role.USER, Message.Role.ASSISTANT)
    ]
    if not turns or turns[-1].role != "user":
        raise ValueError("The conversation must end with a message from you.")

    personality = job_personality(job)
    reply = run_orchestrator_chat(turns, DjangoProjectStore(project, job), personality)
    attachments = _video_attachments(project, reply.production)
    message = Message.objects.create(
        project=project,
        role=Message.Role.ASSISTANT,
        content=reply.content,
        persona=reply.personality,
        attachments=attachments,
        job=job,
    )
    _touch(project)
    return {
        "message_id": message.pk,
        "content": reply.content,
        "attachments": attachments,
        "personality": reply.personality,
        "tools_used": reply.tools_used,
    }


def _run_production(job: GenerationJob, request: ProductionRequest) -> dict[str, Any]:
    project = job.project
    if project is None:
        raise ValueError("Production jobs need a project.")
    personality = job_personality(job)
    result = run_production(DjangoProjectStore(project, job), request, personality)
    attachments = _video_attachments(project, result)
    Message.objects.create(
        project=project,
        role=Message.Role.ASSISTANT,
        content=result["summary"],
        persona=personality,
        attachments=attachments,
        job=job,
    )
    _touch(project)
    return {"report": result, "media": attachments}


@register("production")
def handle_production(job: GenerationJob) -> dict[str, Any]:
    payload = {key: value for key, value in job.input.items() if key != "personality"}
    request = ProductionRequest.model_validate(payload)
    provider = str(job.input.get("narration_provider") or "")
    if provider:
        with narration.project_override(provider):
            return _run_production(job, request)
    return _run_production(job, request)


PREVIEW_KEEP = 12


def preview_dir() -> Path:
    return GENERATED_DIR / "narration-previews"


def preview_file(job_id: str) -> Path | None:
    path = preview_dir() / f"{job_id}.mp3"
    return path if path.is_file() else None


def _prune_previews() -> None:
    files = sorted(preview_dir().glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in files[PREVIEW_KEEP:]:
        stale.unlink(missing_ok=True)


def _config_from_input(data: dict[str, Any]) -> narration.NarrationConfig:
    config = narration.default_config(str(data.get("provider") or "") or None)
    if data.get("voice"):
        config.voice = str(data["voice"])
        config.voice_label = str(data.get("voice_label") or "")
    for control in ("rate", "pitch", "volume"):
        if data.get(control) is not None:
            setattr(config, control, int(data[control]))
    config.source = "request"
    return config


def _narration_preview(job: GenerationJob) -> dict[str, Any]:
    config = _config_from_input(job.input.get("config") or {})
    report("step", agent="narration", stage="narration", status="running")
    speech = narration.synthesize(
        str(job.input.get("text") or ""), preview_dir() / f"{job.pk}.mp3", config
    )
    report("step", agent="narration", stage="narration", status="done")
    _prune_previews()
    return {
        "preview": {
            "url": f"/api/narration/previews/{job.pk}",
            "provider": speech.provider,
            "provider_label": narration.PROVIDER_LABELS[speech.provider],
            "voice": speech.voice,
            "duration_seconds": round(speech.duration_seconds, 2),
            "word_timings": len(speech.words),
        }
    }


def _narration_retry(job: GenerationJob) -> dict[str, Any]:
    """Re-render a legacy narrated short from the spec its failed job kept."""
    from engine.services.video_producer import produce_sound_short_from_spec

    source = GenerationJob.objects.filter(pk=job.input.get("source_job_id")).first()
    spec = (source.error or {}).get("render_spec") if source else None
    if not spec:
        raise ValueError("The original narration details are no longer available.")
    provider = str(job.input.get("provider") or "")
    config = _config_from_input({"provider": provider}) if provider else narration.current_config()
    result = produce_sound_short_from_spec(spec, config)
    media = register_from_result(job, result)
    if job.project is not None:
        Message.objects.create(
            project=job.project,
            role=Message.Role.ASSISTANT,
            content=(
                f"**Narration recorded with {config.label}.** The script and visuals from the "
                "earlier run were reused."
            ),
            persona=job_personality(job),
            attachments=[_attachment(asset) for asset in media if asset.kind != "image"],
            job=job,
        )
        _touch(job.project)
    return {"report": result, "media": [asset_payload(asset) for asset in media]}


@register("narration")
def handle_narration(job: GenerationJob) -> dict[str, Any]:
    mode = job.input.get("mode")
    if mode == "preview":
        return _narration_preview(job)
    if mode == "retry_render":
        return _narration_retry(job)
    raise ValueError(f"Unknown narration job '{mode}'.")


@register("agent")
def handle_agent(job: GenerationJob) -> dict[str, Any]:
    slug = str(job.input.get("slug") or "")
    spec = AGENT_SPECS.get(slug)
    if spec is None:
        raise ValueError(f"Unknown agent '{slug}'.")
    result = run_spec(spec, job.input.get("payload") or {})
    media = register_from_result(job, result) if spec.renders_media else []
    _touch(job.project)
    return {"report": result, "media": [asset_payload(asset) for asset in media]}
