from __future__ import annotations

import uuid
from typing import Any, Literal

from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from pydantic import BaseModel, Field
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from common.files import serve_file
from common.http import ApiError, validate
from engine.llm import ROUTE_LABELS, Route
from engine.orchestrator.registry import list_agents
from engine.orchestrator.schemas import Stage
from engine.services import narration
from engine.services.images.toolkit import ImageToolError
from engine.services.images.variants import VARIANT_SUFFIX
from providers.services import readiness

from . import images, jobs, legacy
from .agent_specs import AGENT_SPECS
from .handlers import preview_file
from .media import MEDIA_TYPES, asset_payload, generated_file
from .models import GenerationJob, MediaAsset, Message, Project
from .serializers import (
    default_personality,
    effective_personality,
    job_payload,
    message_payload,
    production_state,
    project_payload,
)
from .store import detach_asset, replace_scene_asset

DEFAULT_TITLE = "Untitled project"


class ProjectCreate(BaseModel):
    title: str | None = Field(default=None, max_length=120)


NarrationProviderName = Literal["edge", "elevenlabs"]
VOICE_ID = r"^[A-Za-z0-9-]{1,80}$"


class ProjectNarration(BaseModel):
    """``provider=None`` clears the override so the project follows Settings → Narration."""

    provider: NarrationProviderName | None = None
    voice: str = Field(default="", max_length=80, pattern=r"^[A-Za-z0-9-]*$")
    voice_label: str = Field(default="", max_length=160)


PersonalityName = Literal["director", "creative_partner"]


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    narration: ProjectNarration | None = None
    # ``None`` clears the override so the project follows Settings.
    personality: PersonalityName | None = None


class NarrationPreviewConfig(BaseModel):
    provider: NarrationProviderName | None = None
    voice: str | None = Field(default=None, max_length=80, pattern=VOICE_ID)
    voice_label: str | None = Field(default=None, max_length=160)
    rate: int | None = Field(default=None, ge=-50, le=100)
    pitch: int | None = Field(default=None, ge=-50, le=50)
    volume: int | None = Field(default=None, ge=-50, le=50)


class NarrationPreviewCreate(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    config: NarrationPreviewConfig = Field(default_factory=NarrationPreviewConfig)


class NarrationRetryCreate(BaseModel):
    provider: NarrationProviderName | None = None


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class ProductionCreate(BaseModel):
    task: str = Field(min_length=5, max_length=2000)
    context: str | None = Field(default=None, max_length=4000)
    render_video: bool = True
    short_format: Literal["auto", "narrated", "silent", "text_short", "sound_short"] = "auto"
    user_urls: list[str] = Field(default_factory=list, max_length=10)


class ProductionRerun(BaseModel):
    from_stage: Stage | None = None


class ImageSearch(BaseModel):
    query: str = Field(min_length=2, max_length=4000)
    # "link" resolves a link you pasted (e.g. a Google Images result) without fetching Google.
    source: Literal[
        "auto", "pexels", "pixabay", "wikimedia", "openverse", "brave", "url", "webpage", "link"
    ] = "auto"
    orientation: Literal["portrait", "landscape", "square", "any"] = "portrait"
    limit: int = Field(default=12, ge=1, le=20)
    scene_index: int | None = Field(default=None, ge=0, le=20)


class ImageCheck(BaseModel):
    scene_index: int = Field(ge=0, le=20)
    candidate_ids: list[str] = Field(min_length=1, max_length=6)


class ImageDownload(BaseModel):
    candidate_id: str = Field(min_length=3, max_length=200)
    scene_index: int | None = Field(default=None, ge=0, le=20)
    illustrative: bool = False


class SceneImage(BaseModel):
    asset_id: uuid.UUID | None = None
    title_card: bool = False


ALL_ROUTES: tuple[Route, ...] = tuple(ROUTE_LABELS)


def require_ready(routes: tuple[Route, ...]) -> None:
    status_by_route = readiness()
    problems = [status_by_route[r]["problem"] for r in routes if not status_by_route[r]["ready"]]
    if problems:
        raise ApiError(
            " ".join(problems),
            status_code=status.HTTP_409_CONFLICT,
            code="not_configured",
            extra={"readiness": status_by_route, "settings_path": "#/settings"},
        )


def get_project(project_id: uuid.UUID) -> Project:
    return get_object_or_404(Project, pk=project_id)


def get_job(job_id: uuid.UUID) -> GenerationJob:
    return get_object_or_404(GenerationJob, pk=job_id)


def _title_from(text: str) -> str:
    cleaned = " ".join(text.split())
    return cleaned if len(cleaned) <= 60 else f"{cleaned[:60].rstrip()}…"


# --- Projects ----------------------------------------------------------------------------


class ProjectListView(APIView):
    def get(self, request: Request) -> Response:
        last_message = Message.objects.filter(project=OuterRef("pk")).order_by("-created_at", "-id")
        latest_job = GenerationJob.objects.filter(project=OuterRef("pk")).order_by("-created_at")
        projects = (
            Project.objects.all()
            .annotate(
                message_count=Count("messages", distinct=True),
                media_count=Count("media", distinct=True),
                video_count=Count(
                    "media", filter=Q(media__kind=MediaAsset.Kind.VIDEO), distinct=True
                ),
                last_message=Subquery(last_message.values("content")[:1]),
                latest_job_status=Subquery(latest_job.values("status")[:1]),
            )
            .order_by("-updated_at")[:200]
        )
        payload = []
        default = default_personality()
        for project in projects:
            item = project_payload(project, default=default)
            if item["last_message"]:
                item["last_message"] = item["last_message"][:160]
            payload.append(item)
        return Response(payload)

    def post(self, request: Request) -> Response:
        body = validate(ProjectCreate, request.data or {})
        title = (body.title or "").strip()
        project = Project.objects.create(title=title or DEFAULT_TITLE, title_locked=bool(title))
        return Response(project_payload(project), status=status.HTTP_201_CREATED)


class ProjectDetailView(APIView):
    def get(self, request: Request, project_id: uuid.UUID) -> Response:
        project = get_project(project_id)
        jobs.recover_interrupted_jobs()
        messages = list(project.messages.order_by("created_at", "id"))
        jobs_qs = project.jobs.order_by("-created_at")[:50]
        media = project.media.order_by("-created_at")[:100]
        return Response(
            {
                **project_payload(project),
                "messages": [message_payload(m) for m in messages],
                "jobs": [job_payload(j, include_result=False) for j in jobs_qs],
                "media": [asset_payload(a) for a in media],
                "production": production_state(project),
            }
        )

    def patch(self, request: Request, project_id: uuid.UUID) -> Response:
        project = get_project(project_id)
        body = validate(ProjectUpdate, request.data)
        fields = ["updated_at"]
        if body.title is not None:
            title = " ".join(body.title.split())
            if not title:
                raise ApiError("Give the project a title.", code="title_required")
            project.title = title
            project.title_locked = True
            fields += ["title", "title_locked"]
        if "narration" in body.model_fields_set:
            override = body.narration or ProjectNarration()
            project.narration_provider = override.provider or ""
            project.narration_voice = override.voice if override.provider else ""
            project.narration_voice_label = (
                override.voice_label.strip() if override.provider and override.voice else ""
            )
            fields += ["narration_provider", "narration_voice", "narration_voice_label"]
        if "personality" in body.model_fields_set:
            # A running job keeps the personality it started with; the next turn uses this.
            project.personality = body.personality or ""
            fields.append("personality")
        project.save(update_fields=fields)
        payload = project_payload(project)
        payload["personality_applies"] = "next_turn" if _active_job(project) else "now"
        return Response(payload)

    def delete(self, request: Request, project_id: uuid.UUID) -> Response:
        project = get_project(project_id)
        project.jobs.filter(status__in=GenerationJob.ACTIVE).update(cancel_requested=True)
        project.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _active_job(project: Project) -> GenerationJob | None:
    jobs.recover_interrupted_jobs()
    return project.jobs.filter(status__in=GenerationJob.ACTIVE).first()


def _require_idle(project: Project) -> None:
    if _active_job(project):
        raise ApiError(
            "The orchestrator is still working on this project. Wait for it to finish or "
            "cancel it.",
            status_code=409,
            code="job_in_progress",
        )


def _submit_production(
    project: Project,
    request_input: dict[str, Any],
    *,
    summary: str,
    retry_of: GenerationJob | None = None,
) -> tuple[Message, GenerationJob]:
    with transaction.atomic():
        message = Message.objects.create(project=project, role=Message.Role.USER, content=summary)
        project.save(update_fields=["title", "updated_at"])
        job = GenerationJob.objects.create(
            project=project,
            kind=GenerationJob.Kind.PRODUCTION,
            agent="orchestrator",
            input={**request_input, "personality": effective_personality(project)},
            retry_of=retry_of,
        )
        message.job = job
        message.save(update_fields=["job"])
    job = jobs.submit(job)
    message.refresh_from_db()
    return message, job


def _latest_request(project: Project) -> dict[str, Any]:
    """The production request behind the project's current brief."""
    from .models import ProductionTask

    brief = (
        ProductionTask.objects.filter(project=project, stage="brief")
        .exclude(inputs={})
        .order_by("-created_at")
        .first()
    )
    if brief is None or not (brief.inputs or {}).get("task"):
        raise ApiError(
            "This project has no production plan yet. Ask the orchestrator for a video first.",
            status_code=409,
            code="no_plan",
        )
    job = project.jobs.filter(kind=GenerationJob.Kind.PRODUCTION).order_by("-created_at").first()
    user_urls = list((job.input or {}).get("user_urls") or []) if job else []
    return {
        "task": brief.inputs["task"],
        "context": brief.inputs.get("context") or "",
        "short_format": brief.inputs.get("format") or "auto",
        "render_video": True,
        "user_urls": user_urls,
    }


class ProjectMessagesView(APIView):
    def post(self, request: Request, project_id: uuid.UUID) -> Response:
        project = get_project(project_id)
        body = validate(MessageCreate, request.data)
        # The orchestrator may delegate to any specialist from chat, so both routes must work.
        require_ready(ALL_ROUTES)
        _require_idle(project)
        with transaction.atomic():
            message = Message.objects.create(
                project=project, role=Message.Role.USER, content=body.content.strip()
            )
            if not project.title_locked and project.title == DEFAULT_TITLE:
                project.title = _title_from(body.content)
            project.save(update_fields=["title", "updated_at"])
            job = GenerationJob.objects.create(
                project=project,
                kind=GenerationJob.Kind.CHAT,
                agent="orchestrator",
                input={
                    "user_message_id": message.pk,
                    "personality": effective_personality(project),
                },
            )
            message.job = job
            message.save(update_fields=["job"])
        job = jobs.submit(job)
        message.refresh_from_db()
        return Response(
            {
                "message": message_payload(message),
                "job": job_payload(job, events_after=0),
                "project": project_payload(project),
            },
            status=status.HTTP_202_ACCEPTED,
        )


class ProjectProductionView(APIView):
    def post(self, request: Request, project_id: uuid.UUID) -> Response:
        project = get_project(project_id)
        body = validate(ProductionCreate, request.data)
        require_ready(ALL_ROUTES)
        _require_idle(project)
        summary = f"Run a full production: {body.task.strip()}"
        if body.context:
            summary += f"\n\nContext: {body.context.strip()}"
        if not project.title_locked and project.title == DEFAULT_TITLE:
            project.title = _title_from(body.task)
        message, job = _submit_production(
            project,
            {**body.model_dump(), "context": body.context or ""},
            summary=summary,
        )
        return Response(
            {"message": message_payload(message), "job": job_payload(job, events_after=0)},
            status=status.HTTP_202_ACCEPTED,
        )


class ProjectRerunView(APIView):
    """Re-run the current plan. Stages with unchanged inputs are reused, so after a
    scene image changes only the render and quality check run again."""

    def post(self, request: Request, project_id: uuid.UUID) -> Response:
        project = get_project(project_id)
        body = validate(ProductionRerun, request.data or {})
        require_ready(ALL_ROUTES)
        _require_idle(project)
        request_input = _latest_request(project)
        if body.from_stage:
            request_input["from_stage"] = body.from_stage
        label = f"from {body.from_stage}" if body.from_stage else "with the current plan"
        message, job = _submit_production(
            project, request_input, summary=f"Re-run the production {label}."
        )
        return Response(
            {"message": message_payload(message), "job": job_payload(job, events_after=0)},
            status=status.HTTP_202_ACCEPTED,
        )


# --- Project images ----------------------------------------------------------------------


def _image_error(exc: ImageToolError) -> ApiError:
    code = exc.kind if exc.kind else "image_error"
    status_code = 409 if code in ("rights_unknown", "access_denied") else 422
    if code in ("rate_limited",):
        status_code = 429
    return ApiError(str(exc), status_code=status_code, code=code)


class ProjectImageSearchView(APIView):
    """Search the image sources, a direct image URL or a public web page. No model is used."""

    def post(self, request: Request, project_id: uuid.UUID) -> Response:
        project = get_project(project_id)
        body = validate(ImageSearch, request.data)
        try:
            result = images.search(
                project,
                body.query.strip(),
                body.source,
                body.orientation,
                body.limit,
                body.scene_index,
            )
        except ImageToolError as exc:
            raise _image_error(exc) from exc
        return Response(result)


class ProjectImageCheckView(APIView):
    """Check search results against a scene's brief with the Visual specialist model (job)."""

    def post(self, request: Request, project_id: uuid.UUID) -> Response:
        project = get_project(project_id)
        body = validate(ImageCheck, request.data)
        require_ready(("production",))
        try:
            payload = images.check_input(project, body.scene_index, body.candidate_ids)
        except ValueError as exc:
            raise ApiError(str(exc), status_code=409, code="bad_request") from exc
        job = GenerationJob.objects.create(
            project=project, kind=GenerationJob.Kind.IMAGE_CHECK, agent="visual", input=payload
        )
        job = jobs.submit(job)
        return Response(job_payload(job, events_after=0), status=status.HTTP_202_ACCEPTED)


class ProjectImageDownloadView(APIView):
    def post(self, request: Request, project_id: uuid.UUID) -> Response:
        project = get_project(project_id)
        body = validate(ImageDownload, request.data)
        if body.scene_index is not None:
            _require_idle(project)
        try:
            saved, visuals = images.download(
                project, body.candidate_id, body.scene_index, illustrative=body.illustrative
            )
        except ImageToolError as exc:
            raise _image_error(exc) from exc
        except ValueError as exc:
            raise ApiError(str(exc), status_code=409, code="bad_request") from exc
        asset = MediaAsset.objects.get(pk=saved["asset_id"])
        return Response(
            {
                "asset": asset_payload(asset),
                "reused_existing_file": saved["reused_existing_file"],
                "production": production_state(project) if visuals is not None else None,
            },
            status=status.HTTP_201_CREATED,
        )


class ProjectImageUploadView(APIView):
    """Add an image file from the user's computer, optionally assigning it to a scene."""

    def post(self, request: Request, project_id: uuid.UUID) -> Response:
        project = get_project(project_id)
        upload = request.FILES.get("file")
        if upload is None:
            raise ApiError("Choose an image file to upload.", code="bad_request")
        raw_scene = request.data.get("scene_index")
        scene_index: int | None = None
        if raw_scene not in (None, ""):
            try:
                scene_index = int(raw_scene)
            except (TypeError, ValueError) as exc:
                raise ApiError("scene_index must be a number.", code="bad_request") from exc
            _require_idle(project)
        try:
            saved, visuals = images.upload(project, upload, scene_index)
        except ImageToolError as exc:
            raise _image_error(exc) from exc
        except ValueError as exc:
            raise ApiError(str(exc), status_code=409, code="bad_request") from exc
        asset = MediaAsset.objects.get(pk=saved["asset_id"])
        return Response(
            {
                "asset": asset_payload(asset),
                "reused_existing_file": saved["reused_existing_file"],
                "production": production_state(project) if visuals is not None else None,
            },
            status=status.HTTP_201_CREATED,
        )


class ProjectSceneImageView(APIView):
    """Point a scene at another project image, clear it (``asset_id: null``), or choose a
    title card (``title_card: true``)."""

    def put(self, request: Request, project_id: uuid.UUID, scene_index: int) -> Response:
        project = get_project(project_id)
        body = validate(SceneImage, request.data or {})
        _require_idle(project)
        if body.title_card:
            try:
                replace_scene_asset(project, scene_index, None, title_card=True)
            except ValueError as exc:
                raise ApiError(str(exc), status_code=409, code="bad_request") from exc
            return Response(production_state(project))
        asset = None
        if body.asset_id is not None:
            asset = MediaAsset.objects.filter(
                pk=body.asset_id, project=project, kind=MediaAsset.Kind.IMAGE
            ).first()
            if asset is None or generated_file(asset.file_name) is None:
                raise ApiError(
                    "That image isn't in this project.", status_code=404, code="not_found"
                )
        try:
            replace_scene_asset(project, scene_index, asset)
        except ValueError as exc:
            raise ApiError(str(exc), status_code=409, code="bad_request") from exc
        return Response(production_state(project))


# --- Jobs --------------------------------------------------------------------------------


class JobListView(APIView):
    def get(self, request: Request) -> Response:
        jobs.recover_interrupted_jobs()
        queryset = GenerationJob.objects.all()
        project = request.query_params.get("project")
        if project:
            try:
                queryset = queryset.filter(project_id=uuid.UUID(project))
            except ValueError as exc:
                raise ApiError("Invalid project id.", code="invalid_id") from exc
        state = request.query_params.get("status")
        if state == "active":
            queryset = queryset.filter(status__in=GenerationJob.ACTIVE)
        elif state:
            queryset = queryset.filter(status=state)
        try:
            limit = max(1, min(100, int(request.query_params.get("limit", 30))))
        except ValueError:
            limit = 30
        return Response(
            [
                job_payload(job, include_result=False)
                for job in queryset.order_by("-created_at")[:limit]
            ]
        )


class JobDetailView(APIView):
    def get(self, request: Request, job_id: uuid.UUID) -> Response:
        jobs.recover_interrupted_jobs()
        job = get_job(job_id)
        try:
            after = max(0, int(request.query_params.get("after", 0)))
        except ValueError:
            after = 0
        return Response(job_payload(job, events_after=after))


class JobCancelView(APIView):
    def post(self, request: Request, job_id: uuid.UUID) -> Response:
        job = get_job(job_id)
        if job.status == GenerationJob.Status.QUEUED:
            GenerationJob.objects.filter(pk=job.pk, status=GenerationJob.Status.QUEUED).update(
                cancel_requested=True
            )
        elif job.status == GenerationJob.Status.RUNNING:
            GenerationJob.objects.filter(pk=job.pk).update(cancel_requested=True)
        job.refresh_from_db()
        return Response(job_payload(job, events_after=0))


class JobRetryView(APIView):
    def post(self, request: Request, job_id: uuid.UUID) -> Response:
        job = get_job(job_id)
        if job.is_active:
            raise ApiError("This job is still running.", status_code=409, code="job_in_progress")
        if job.status == GenerationJob.Status.SUCCEEDED:
            raise ApiError("This job already succeeded.", status_code=409, code="job_succeeded")
        routes: tuple[Route, ...] = (
            ()
            if job.kind == GenerationJob.Kind.NARRATION
            else AGENT_SPECS[job.input.get("slug", "")].routes
            if job.kind == GenerationJob.Kind.AGENT and job.input.get("slug") in AGENT_SPECS
            else ALL_ROUTES
        )
        require_ready(routes)
        if job.project_id and _active_job(job.project):
            raise ApiError(
                "Another job is running on this project.", status_code=409, code="job_in_progress"
            )
        retry_input = dict(job.input or {})
        if job.project is not None and "personality" in retry_input:
            # A retry is a new turn, so it speaks with the personality chosen now.
            retry_input["personality"] = effective_personality(job.project)
        with transaction.atomic():
            retry = GenerationJob.objects.create(
                project=job.project,
                kind=job.kind,
                agent=job.agent,
                input=retry_input,
                retry_of=job,
            )
            Message.objects.filter(job=job, role=Message.Role.USER).update(job=retry)
        retry = jobs.submit(retry)
        return Response(job_payload(retry, events_after=0), status=status.HTTP_202_ACCEPTED)


class JobRetryNarrationView(APIView):
    """Re-record narration for a failed render, reusing its script and visuals."""

    def post(self, request: Request, job_id: uuid.UUID) -> Response:
        job = get_job(job_id)
        body = validate(NarrationRetryCreate, request.data or {})
        error = job.error or {}
        if job.status != GenerationJob.Status.FAILED or error.get("kind") != "narration_failed":
            raise ApiError(
                "Only a job that failed while recording narration can retry narration.",
                status_code=409,
                code="not_a_narration_failure",
            )
        if not error.get("render_spec"):
            raise ApiError(
                "This job didn't keep enough detail to retry narration on its own. Retry the "
                "whole job instead.",
                status_code=409,
                code="narration_spec_missing",
            )
        if job.project_id and _active_job(job.project):
            raise ApiError(
                "Another job is running on this project.", status_code=409, code="job_in_progress"
            )
        _require_narration_ready(body.provider, job.project)
        spec = error["render_spec"]
        if spec.get("resume_production") and job.project is not None:
            # Orchestrated productions resume from narration; script and images are reused.
            source_input = (
                job.input
                if job.kind == GenerationJob.Kind.PRODUCTION
                else _latest_request(job.project)
            )
            request_input = {
                key: value for key, value in source_input.items() if key != "personality"
            }
            request_input.update(
                from_stage="narration", narration_provider=body.provider or "", stop_after=None
            )
            if job.kind == GenerationJob.Kind.CHAT:
                request_input.setdefault("render_video", True)
            message, retry = _submit_production(
                job.project, request_input, summary="Retry narration.", retry_of=job
            )
            return Response(job_payload(retry, events_after=0), status=status.HTTP_202_ACCEPTED)
        retry = GenerationJob.objects.create(
            project=job.project,
            kind=GenerationJob.Kind.NARRATION,
            agent="voice",
            input={
                "mode": "retry_render",
                "source_job_id": str(job.pk),
                "provider": body.provider or "",
            },
            retry_of=job,
        )
        retry = jobs.submit(retry)
        return Response(job_payload(retry, events_after=0), status=status.HTTP_202_ACCEPTED)


# --- Narration ---------------------------------------------------------------------------


def _require_narration_ready(provider: str | None, project: Project | None = None) -> None:
    with narration.project_override(
        project.narration_provider if project else "",
        project.narration_voice if project else "",
        project.narration_voice_label if project else "",
    ):
        config = narration.default_config(provider) if provider else narration.current_config()
    state = narration.readiness(config)
    if not state["ready"]:
        raise ApiError(
            str(state["problem"]),
            status_code=status.HTTP_409_CONFLICT,
            code="not_configured",
            extra={"service": config.provider, "settings_path": "#/settings/narration"},
        )


class NarrationPreviewView(APIView):
    """Record a short sample. Runs only when the user clicks Preview."""

    def post(self, request: Request) -> Response:
        body = validate(NarrationPreviewCreate, request.data)
        _require_narration_ready(body.config.provider)
        job = GenerationJob.objects.create(
            kind=GenerationJob.Kind.NARRATION,
            agent="voice",
            input={
                "mode": "preview",
                "text": " ".join(body.text.split()),
                "config": body.config.model_dump(exclude_none=True),
            },
        )
        job = jobs.submit(job)
        return Response(job_payload(job, events_after=0), status=status.HTTP_202_ACCEPTED)


class NarrationPreviewFileView(APIView):
    def get(self, request: Request, job_id: uuid.UUID) -> Any:
        job = get_job(job_id)
        path = preview_file(str(job.pk)) if job.kind == GenerationJob.Kind.NARRATION else None
        if path is None:
            raise ApiError(
                "This preview has expired. Record it again.", status_code=404, code="file_missing"
            )
        return serve_file(
            request._request, path, content_type="audio/mpeg", download_name="preview.mp3"
        )


# --- Agents ------------------------------------------------------------------------------


class AgentRegistryView(APIView):
    def get(self, request: Request) -> Response:
        return Response(list_agents())


class AgentStatusView(APIView):
    def get(self, request: Request) -> Response:
        return Response(
            {
                "routes": readiness(),
                "route_labels": ROUTE_LABELS,
                "endpoints": [
                    {"slug": spec.slug, "agent": spec.agent_id, "label": spec.label}
                    for spec in AGENT_SPECS.values()
                ],
            }
        )


class AgentJobView(APIView):
    """Queue one specialist agent. Returns 202 with a job to poll."""

    def post(self, request: Request, slug: str) -> Response:
        spec = AGENT_SPECS.get(slug)
        if spec is None:
            raise ApiError(f"Unknown agent “{slug}”.", status_code=404, code="unknown_agent")
        payload = request.data if isinstance(request.data, dict) else {}
        project_id = payload.pop("project_id", None) if isinstance(payload, dict) else None
        validate(spec.request_model, payload)
        require_ready(spec.routes)
        project = None
        if project_id:
            try:
                project = get_project(uuid.UUID(str(project_id)))
            except ValueError as exc:
                raise ApiError("Invalid project id.", code="invalid_id") from exc
        job = GenerationJob.objects.create(
            project=project,
            kind=GenerationJob.Kind.AGENT,
            agent=spec.agent_id,
            input={"slug": slug, "payload": payload},
        )
        job = jobs.submit(job)
        return Response(job_payload(job, events_after=0), status=status.HTTP_202_ACCEPTED)


# --- Media -------------------------------------------------------------------------------


class MediaListView(APIView):
    def get(self, request: Request) -> Response:
        queryset = MediaAsset.objects.all()
        kind = request.query_params.get("kind")
        if kind in ("video", "audio", "image"):
            queryset = queryset.filter(kind=kind)
        project = request.query_params.get("project")
        if project:
            try:
                queryset = queryset.filter(project_id=uuid.UUID(project))
            except ValueError as exc:
                raise ApiError("Invalid project id.", code="invalid_id") from exc
        return Response([asset_payload(a) for a in queryset.order_by("-created_at")[:500]])


class MediaDetailView(APIView):
    def delete(self, request: Request, asset_id: uuid.UUID) -> Response:
        asset = get_object_or_404(MediaAsset, pk=asset_id)
        if asset.project is not None and _active_job(asset.project):
            raise ApiError(
                "Wait for the current job to finish before deleting project media.",
                status_code=409,
                code="job_in_progress",
            )
        path = generated_file(asset.file_name)
        detach_asset(asset)
        asset.delete()
        if path is not None:
            path.unlink(missing_ok=True)
            path.with_name(path.stem + VARIANT_SUFFIX).unlink(missing_ok=True)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _serve_asset(request: Request, asset: MediaAsset) -> Any:
    path = generated_file(asset.file_name)
    if path is None:
        raise ApiError(
            "The file is missing from the output folder.", status_code=404, code="file_missing"
        )
    return serve_file(
        request._request,
        path,
        content_type=MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        download_name=asset.display_name,
        as_attachment=request.query_params.get("download") in ("1", "true"),
    )


class MediaFileView(APIView):
    def get(self, request: Request, asset_id: uuid.UUID) -> Any:
        asset = get_object_or_404(MediaAsset, pk=asset_id)
        return _serve_asset(request, asset)


# --- Legacy compatibility ------------------------------------------------------------------


class HealthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


class LegacyVideoListView(APIView):
    def get(self, request: Request) -> Response:
        videos = MediaAsset.objects.filter(kind=MediaAsset.Kind.VIDEO)
        return Response(
            [
                {
                    "url": f"/api/media/{asset.pk}/file",
                    "filename": asset.display_name,
                    "created_at": int(asset.created_at.timestamp()),
                }
                for asset in videos.order_by("-created_at")
            ]
        )


class LegacyFileView(APIView):
    """Old attachment URLs (/api/chat/videos/<file>) keep working."""

    def get(self, request: Request, file_name: str) -> Any:
        asset = get_object_or_404(MediaAsset, file_name=file_name)
        return _serve_asset(request, asset)


class LegacyImportView(APIView):
    def post(self, request: Request) -> Response:
        body = validate(legacy.LegacyImport, request.data)
        dry_run = request.query_params.get("dry_run") in ("1", "true")
        report = legacy.import_chats(body, dry_run=dry_run)
        return Response({"dry_run": dry_run, **report.to_dict()})
