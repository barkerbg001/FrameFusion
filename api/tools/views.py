"""Utility endpoints: stock media, reference lookups, and direct render tools."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from pydantic import BaseModel, Field, field_validator
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from common.http import ApiError, validate
from engine.schemas.video import SoundVideoRequest, TextShortRequest
from engine.schemas.video_tools import SoundShortProductionRequest, TextShortProductionRequest
from studio import jobs
from studio.models import GenerationJob
from studio.serializers import job_payload

from .handlers import upload_dir

AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_IMAGES = 50


def _upstream(exc: Exception, not_found: tuple[type[Exception], ...]) -> ApiError:
    if isinstance(exc, ValueError):
        return ApiError(str(exc), code="bad_request")
    if isinstance(exc, not_found):
        return ApiError(str(exc), status_code=404, code="not_found")
    return ApiError(str(exc), status_code=502, code="upstream_error")


# --- Lookups -------------------------------------------------------------------------------


class PexelsQuery(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    per_page: int = Field(default=15, ge=1, le=80)
    page: int = Field(default=1, ge=1)
    orientation: Literal["landscape", "portrait", "square", "any"] | None = None
    size: Literal["large", "medium", "small", "any"] | None = None
    media_type: Literal["photo", "video", "both"] | None = None


class PexelsView(APIView):
    """Search Pexels with the saved key. Omitted filters use the Settings defaults;
    ``any`` clears a saved default for this request."""

    mode: str = "both"

    def get(self, request: Request) -> Response:
        from engine.services import pexels_client as pexels

        q = validate(PexelsQuery, request.query_params.dict())

        def pick(value: str | None) -> Any:
            if value is None:
                return pexels.USE_DEFAULT
            return None if value == "any" else value

        filters = {"orientation": pick(q.orientation), "size": pick(q.size)}
        try:
            if self.mode == "photos":
                result = pexels.search_pexels_photos(
                    q.query, per_page=q.per_page, page=q.page, **filters
                )
            elif self.mode == "videos":
                result = pexels.search_pexels_videos(
                    q.query, per_page=q.per_page, page=q.page, **filters
                )
            else:
                result = pexels.search_pexels(
                    q.query, media_type=q.media_type, per_page=q.per_page, page=q.page, **filters
                )
        except (ValueError, pexels.PexelsNotFoundError, pexels.PexelsServiceError) as exc:
            raise _upstream(exc, (pexels.PexelsNotFoundError,)) from exc
        return Response(result)


class PokemonView(APIView):
    def get(self, request: Request, identifier: str) -> Response:
        from engine.services import pokemon_client as pokemon

        if not 1 <= len(identifier) <= 100:
            raise ApiError("identifier must be 1–100 characters.", code="validation_error")
        try:
            return Response(pokemon.get_pokemon_data(identifier))
        except pokemon.PokemonNotFoundError as exc:
            raise ApiError(
                f"Pokemon '{identifier}' was not found", status_code=404, code="not_found"
            ) from exc
        except (ValueError, pokemon.PokemonServiceError) as exc:
            raise _upstream(exc, ()) from exc


class WeatherQuery(BaseModel):
    location: str = Field(min_length=2, max_length=150)


class WeatherView(APIView):
    def get(self, request: Request) -> Response:
        from engine.services import weather_client as weather

        q = validate(WeatherQuery, request.query_params.dict())
        try:
            return Response(weather.get_current_weather(q.location))
        except (ValueError, weather.LocationNotFoundError, weather.WeatherServiceError) as exc:
            raise _upstream(exc, (weather.LocationNotFoundError,)) from exc


class TimeQuery(BaseModel):
    timezone: str = Field(default="UTC", min_length=1, max_length=100)


class TimeView(APIView):
    def get(self, request: Request) -> Response:
        from engine.services.time_tool import get_current_time

        q = validate(TimeQuery, request.query_params.dict())
        try:
            return Response(get_current_time(q.timezone))
        except ValueError as exc:
            raise ApiError(str(exc), code="bad_request") from exc


class WikipediaQuery(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    max_sources: int = Field(default=3, ge=1, le=5)


class WikipediaView(APIView):
    def get(self, request: Request) -> Response:
        from engine.services import wikipedia_client as wiki

        q = validate(WikipediaQuery, request.query_params.dict())
        try:
            return Response(wiki.search_wikipedia(q.query, q.max_sources))
        except (ValueError, wiki.WikipediaNotFoundError, wiki.WikipediaServiceError) as exc:
            raise _upstream(exc, (wiki.WikipediaNotFoundError,)) from exc


# --- Render jobs ----------------------------------------------------------------------------


def _queue_render(
    request: Request,
    tool: str,
    data: dict[str, Any],
    files: dict[str, UploadedFile] | None = None,
) -> Response:
    with transaction.atomic():
        job = GenerationJob.objects.create(
            kind=GenerationJob.Kind.RENDER,
            agent="renderer",
            input={"tool": tool, **data},
        )
    if files:
        folder = upload_dir(job.pk)
        for name, upload in files.items():
            with (folder / name).open("wb") as handle:
                for chunk in upload.chunks():
                    handle.write(chunk)
    job = jobs.submit(job)
    return Response(job_payload(job, events_after=0), status=status.HTTP_202_ACCEPTED)


def _check_upload(upload: UploadedFile | None, allowed: set[str], label: str) -> str:
    if upload is None:
        raise ApiError(f"{label} file is required.", code="validation_error")
    suffix = Path(upload.name or "").suffix.lower()
    if suffix not in allowed:
        raise ApiError(
            f"Unsupported {label.lower()} format. Use one of: {', '.join(sorted(allowed))}",
            code="unsupported_format",
        )
    if upload.size and upload.size > settings.FRAMEFUSION_MAX_UPLOAD_BYTES:
        limit = settings.FRAMEFUSION_MAX_UPLOAD_BYTES // (1024 * 1024)
        raise ApiError(f"{label} file is larger than {limit} MB.", code="file_too_large")
    return suffix


def _safe_mp4_name(value: str, default: str) -> str:
    value = (value or default).strip()
    if value != Path(value).name or "\\" in value or not value.lower().endswith(".mp4"):
        raise ApiError(
            "output_name must be an .mp4 filename without a path", code="validation_error"
        )
    return value


class TextVideoView(APIView):
    def post(self, request: Request) -> Response:
        body = validate(TextShortRequest, request.data)
        return _queue_render(request, "text_video", body.model_dump())


class AudioVideoForm(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    background_color: str | None = None
    text_color: str = "#FFFFFF"
    font_size: int = Field(default=96, ge=36, le=180)
    output_name: str = "sound-short.mp4"

    @field_validator("text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value.strip()

    @field_validator("background_color", "text_color")
    @classmethod
    def hex_color(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not re.fullmatch(r"#[0-9A-F]{6}", normalized):
            raise ValueError("color must use the #RRGGBB format")
        return normalized


class AudioVideoView(APIView):
    def post(self, request: Request) -> Response:
        form = {k: v for k, v in request.data.items() if k != "audio" and v != ""}
        body = validate(AudioVideoForm, form)
        audio = request.FILES.get("audio")
        suffix = _check_upload(audio, AUDIO_EXTENSIONS, "Audio")
        output_name = _safe_mp4_name(body.output_name, "sound-short.mp4")
        audio_name = f"audio{suffix}"
        return _queue_render(
            request,
            "audio_video",
            {**body.model_dump(), "output_name": output_name, "audio_file": audio_name},
            {audio_name: audio},
        )


class SoundVideoView(APIView):
    def post(self, request: Request) -> Response:
        body = validate(SoundVideoRequest, request.data)
        return _queue_render(request, "sound_video", body.model_dump())


class LofiForm(BaseModel):
    output_name: str = "output.mp4"
    repeat_minutes: int = Field(default=60, ge=1, le=180)


class LofiView(APIView):
    def post(self, request: Request) -> Response:
        body = validate(
            LofiForm,
            {
                k: request.data.get(k)
                for k in ("output_name", "repeat_minutes")
                if request.data.get(k) not in (None, "")
            },
        )
        images = request.FILES.getlist("images")
        if not images:
            raise ApiError("Add at least one image.", code="validation_error")
        if len(images) > MAX_IMAGES:
            raise ApiError(f"Use at most {MAX_IMAGES} images.", code="validation_error")
        audio = request.FILES.get("audio")
        audio_suffix = _check_upload(audio, AUDIO_EXTENSIONS, "Audio")
        files: dict[str, UploadedFile] = {f"audio{audio_suffix}": audio}
        image_names = []
        for index, image in enumerate(images):
            suffix = _check_upload(image, IMAGE_EXTENSIONS, "Image")
            name = f"image-{index:03d}{suffix}"
            files[name] = image
            image_names.append(name)
        return _queue_render(
            request,
            "lofi",
            {
                "output_name": _safe_mp4_name(body.output_name, "output.mp4"),
                "repeat_minutes": body.repeat_minutes,
                "audio_file": f"audio{audio_suffix}",
                "image_files": image_names,
            },
            files,
        )


class ProducerTextShortView(APIView):
    def post(self, request: Request) -> Response:
        body = validate(TextShortProductionRequest, request.data)
        return _queue_render(request, "producer_short", {"mode": "text", "text": body.text})


class ProducerSoundShortView(APIView):
    def post(self, request: Request) -> Response:
        body = validate(SoundShortProductionRequest, request.data)
        return _queue_render(request, "producer_short", {"mode": "sound", "text": body.text})
