from __future__ import annotations

from typing import Any, Literal

from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from pydantic import BaseModel, Field, field_validator
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from common.http import ApiError, validate
from engine.orchestrator import personalities
from engine.services import edge_tts_client, narration

from . import account_import, services
from .clients import CLIENTS
from .clients.media import MEDIA_CLIENTS, MUSIC_MODELS, PREVIEW_MAX_CHARS, ElevenLabsClient
from .crypto import encryption_configured
from .models import AgentModelOverride, AppSettings, ImportedSettingChoice

ProviderName = Literal["openrouter", "gemini", "anthropic"]
ThemeName = Literal["system", "dark", "light"]
OnboardingStep = Literal[
    "welcome", "providers", "models", "narration", "media", "appearance", "review"
]


def _service(name: str) -> str:
    if name not in CLIENTS and name not in MEDIA_CLIENTS:
        raise ApiError(f"Unknown integration “{name}”.", status_code=404, code="unknown_provider")
    return name


def _ai_provider(name: str) -> str:
    if name not in CLIENTS:
        raise ApiError(f"Unknown provider “{name}”.", status_code=404, code="unknown_provider")
    return name


class KeyBody(BaseModel):
    api_key: str = Field(min_length=8, max_length=512)

    @field_validator("api_key")
    @classmethod
    def no_whitespace(cls, value: str) -> str:
        value = value.strip()
        if any(ch.isspace() for ch in value):
            raise ValueError("API keys cannot contain spaces or line breaks.")
        return value


class TestBody(BaseModel):
    api_key: str | None = Field(default=None, min_length=8, max_length=512)


class OverrideBody(BaseModel):
    provider: ProviderName
    model: str = Field(min_length=1, max_length=200)


class AISettingsBody(BaseModel):
    default_provider: ProviderName | None = None
    default_model: str = Field(default="", max_length=200)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=256, le=65536)
    overrides: dict[Literal["planner", "production"], OverrideBody | None] = Field(
        default_factory=dict
    )


class VoiceSettingsBody(BaseModel):
    stability: float | None = Field(default=None, ge=0, le=1)
    similarity_boost: float | None = Field(default=None, ge=0, le=1)
    style: float | None = Field(default=None, ge=0, le=1)
    speed: float | None = Field(default=None, ge=0.7, le=1.2)
    use_speaker_boost: bool | None = None

    def api_payload(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class ElevenLabsSettingsBody(BaseModel):
    voice_id: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9]*$")
    voice_name: str = Field(default="", max_length=120)
    model_id: str = Field(default="eleven_multilingual_v2", min_length=1, max_length=80)
    music_model: Literal["music_v1", "music_v2"] = "music_v2"
    voice_settings: VoiceSettingsBody = Field(default_factory=VoiceSettingsBody)


class PexelsSettingsBody(BaseModel):
    media_type: Literal["video", "photo", "both"] = "video"
    orientation: Literal["", "landscape", "portrait", "square"] = "portrait"
    size: Literal["", "large", "medium", "small"] = ""


class MediaSettingsBody(BaseModel):
    elevenlabs: ElevenLabsSettingsBody | None = None
    pexels: PexelsSettingsBody | None = None


class EdgeSettingsBody(BaseModel):
    voice: str = Field(min_length=3, max_length=80, pattern=edge_tts_client.VOICE_PATTERN.pattern)
    voice_label: str = Field(default="", max_length=160)
    rate: int = Field(default=0, ge=edge_tts_client.RATE_RANGE[0], le=edge_tts_client.RATE_RANGE[1])
    pitch: int = Field(
        default=0, ge=edge_tts_client.PITCH_RANGE[0], le=edge_tts_client.PITCH_RANGE[1]
    )
    volume: int = Field(
        default=0, ge=edge_tts_client.VOLUME_RANGE[0], le=edge_tts_client.VOLUME_RANGE[1]
    )


class NarrationSettingsBody(BaseModel):
    provider: Literal["edge", "elevenlabs"]
    edge: EdgeSettingsBody | None = None


class AppearanceBody(BaseModel):
    theme: ThemeName


class PersonalityBody(BaseModel):
    personality: Literal["director", "creative_partner"]


class OnboardingBody(BaseModel):
    step: OnboardingStep | None = None
    skip: OnboardingStep | None = None
    complete: bool = False
    restart: bool = False


class ChoiceBody(BaseModel):
    choice: str = Field(min_length=1, max_length=64)


# --- App bootstrap --------------------------------------------------------------------------


def onboarding_payload(app: AppSettings) -> dict[str, Any]:
    return {
        "steps": list(AppSettings.ONBOARDING_STEPS),
        "step": app.onboarding_step,
        "skipped": list(app.onboarding_skipped or []),
        "completed": app.onboarding_completed_at is not None,
        "completed_at": (
            app.onboarding_completed_at.isoformat() if app.onboarding_completed_at else None
        ),
    }


def app_payload() -> dict[str, Any]:
    app = AppSettings.load()
    return {
        "theme": app.theme,
        "personality": app.orchestrator_personality,
        "personalities": personalities.catalogue(),
        "onboarding": onboarding_payload(app),
        "encryption_configured": encryption_configured(),
        "readiness": services.readiness(),
        "integrations": services.integrations_status(),
        "narration": narration.readiness(narration.default_config()),
        "pending_import_choices": ImportedSettingChoice.objects.filter(
            status=ImportedSettingChoice.Status.PENDING
        ).count(),
    }


@method_decorator(ensure_csrf_cookie, name="get")
class AppView(APIView):
    """First request the web app makes; also sets the CSRF cookie."""

    def get(self, request: Request) -> Response:
        return Response(app_payload())


class AppearanceView(APIView):
    def put(self, request: Request) -> Response:
        body = validate(AppearanceBody, request.data)
        app = AppSettings.load()
        app.theme = body.theme
        app.save(update_fields=["theme", "updated_at"])
        return Response({"theme": app.theme})


class PersonalityView(APIView):
    """Default orchestrator personality. Running jobs keep the one they started with."""

    def put(self, request: Request) -> Response:
        body = validate(PersonalityBody, request.data)
        app = AppSettings.load()
        app.orchestrator_personality = body.personality
        app.save(update_fields=["orchestrator_personality", "updated_at"])
        return Response({"personality": app.orchestrator_personality})


class OnboardingView(APIView):
    def get(self, request: Request) -> Response:
        return Response(onboarding_payload(AppSettings.load()))

    def put(self, request: Request) -> Response:
        body = validate(OnboardingBody, request.data)
        with transaction.atomic():
            app = AppSettings.load()
            skipped = [
                s for s in (app.onboarding_skipped or []) if s in AppSettings.ONBOARDING_STEPS
            ]
            if body.restart:
                app.onboarding_step = "welcome"
                app.onboarding_completed_at = None
                skipped = []
            if body.skip and body.skip not in skipped:
                skipped.append(body.skip)
            if body.step:
                app.onboarding_step = body.step
                if body.step in skipped and body.step != body.skip:
                    skipped.remove(body.step)
            if body.complete:
                app.onboarding_completed_at = timezone.now()
            app.onboarding_skipped = skipped
            app.save()
        return Response(onboarding_payload(app))


# --- Credentials ----------------------------------------------------------------------------


class ProvidersView(APIView):
    def get(self, request: Request) -> Response:
        return Response(
            {
                "encryption_configured": encryption_configured(),
                "providers": services.all_credentials_payload(),
            }
        )


class ProviderKeyView(APIView):
    def put(self, request: Request, provider: str) -> Response:
        service = _service(provider)
        body = validate(KeyBody, request.data)
        credential = services.save_api_key(service, body.api_key)
        return Response(services.credential_payload(service, credential))

    def delete(self, request: Request, provider: str) -> Response:
        service = _service(provider)
        services.delete_api_key(service)
        return Response(services.credential_payload(service, None))


class ProviderTestView(APIView):
    def post(self, request: Request, provider: str) -> Response:
        service = _service(provider)
        body = validate(TestBody, request.data or {})
        credential = services.get_credential(service)
        if body.api_key:
            api_key = body.api_key.strip()
        elif credential is not None:
            api_key = services.get_api_key(service)
        else:
            raise ApiError("Enter an API key to test, or save one first.", code="no_key_to_test")
        result = services.test_connection(service, api_key)
        if credential is not None and not body.api_key:
            services.record_test(credential, result)
        return Response(
            {
                "result": result.to_dict(),
                "tested": "unsaved_key" if body.api_key else "saved_key",
                "provider": services.credential_payload(service, credential),
            }
        )


class ProviderModelsView(APIView):
    def get(self, request: Request, provider: str) -> Response:
        provider = _ai_provider(provider)
        refresh = request.query_params.get("refresh") in ("1", "true")
        return Response({"provider": provider, **services.list_models(provider, refresh=refresh)})


# --- AI routing -----------------------------------------------------------------------------


def ai_settings_payload() -> dict[str, Any]:
    app = AppSettings.load()
    overrides = {o.persona: o for o in AgentModelOverride.objects.all()}
    return {
        "default_provider": app.default_provider or None,
        "default_model": app.default_model,
        "temperature": app.temperature,
        "max_output_tokens": app.max_output_tokens,
        "overrides": {
            route: (
                {"provider": overrides[route].provider, "model": overrides[route].model}
                if route in overrides
                else None
            )
            for route in services.ROUTES
        },
        "readiness": services.readiness(),
        "capabilities": {name: client.info.capabilities for name, client in CLIENTS.items()},
        "notes": {
            "anthropic_temperature_max": 1.0,
        },
    }


class AISettingsView(APIView):
    def get(self, request: Request) -> Response:
        return Response(ai_settings_payload())

    def put(self, request: Request) -> Response:
        body = validate(AISettingsBody, request.data)
        if body.default_provider and not body.default_model.strip():
            raise ApiError(
                "Choose a default model for the selected provider.", code="model_required"
            )
        with transaction.atomic():
            app = AppSettings.load()
            app.default_provider = body.default_provider or ""
            app.default_model = body.default_model.strip() if body.default_provider else ""
            app.temperature = body.temperature
            app.max_output_tokens = body.max_output_tokens
            app.save()
            for route, override in body.overrides.items():
                if override is None:
                    AgentModelOverride.objects.filter(persona=route).delete()
                else:
                    AgentModelOverride.objects.update_or_create(
                        persona=route,
                        defaults={"provider": override.provider, "model": override.model.strip()},
                    )
        return Response(ai_settings_payload())


# --- Media integrations ---------------------------------------------------------------------


def media_payload() -> dict[str, Any]:
    return {
        **services.media_settings_payload(),
        "integrations": services.integrations_status(),
        "music_models": MUSIC_MODELS,
    }


class MediaSettingsView(APIView):
    def get(self, request: Request) -> Response:
        return Response(media_payload())

    def put(self, request: Request) -> Response:
        body = validate(MediaSettingsBody, request.data)
        app = AppSettings.load()
        if body.elevenlabs is not None:
            el = body.elevenlabs
            vs = el.voice_settings
            app.elevenlabs_voice_id = el.voice_id
            app.elevenlabs_voice_name = el.voice_name.strip() if el.voice_id else ""
            app.elevenlabs_model_id = el.model_id.strip()
            app.elevenlabs_music_model = el.music_model
            app.elevenlabs_stability = vs.stability
            app.elevenlabs_similarity_boost = vs.similarity_boost
            app.elevenlabs_style = vs.style
            app.elevenlabs_speed = vs.speed
            app.elevenlabs_speaker_boost = vs.use_speaker_boost
        if body.pexels is not None:
            app.pexels_media_type = body.pexels.media_type
            app.pexels_orientation = body.pexels.orientation
            app.pexels_size = body.pexels.size
        app.save()
        return Response(media_payload())


def _elevenlabs() -> ElevenLabsClient:
    client = services.media_client("elevenlabs", services.get_api_key("elevenlabs"))
    assert isinstance(client, ElevenLabsClient)
    return client


class ElevenLabsVoicesView(APIView):
    def get(self, request: Request) -> Response:
        page = _elevenlabs().list_voices(
            search=request.query_params.get("search", "").strip(),
            next_page_token=request.query_params.get("next_page_token") or None,
        )
        return Response(
            {
                "voices": page.voices,
                "has_more": page.has_more,
                "next_page_token": page.next_page_token,
            }
        )


class ElevenLabsModelsView(APIView):
    def get(self, request: Request) -> Response:
        return Response({"models": _elevenlabs().list_models(), "music_models": MUSIC_MODELS})


# --- Narration ------------------------------------------------------------------------------

EDGE_DISCLOSURE = (
    "Edge TTS is free and needs no API key, but it is an online service: the text you narrate "
    "is sent to Microsoft's speech service over the internet. It is an unofficial client, so "
    "availability, limits and terms can change without notice."
)


def narration_payload() -> dict[str, Any]:
    saved = services.narration_settings_payload()
    return {
        **saved,
        "readiness": narration.readiness(narration.default_config()),
        "providers": [
            {
                "id": "edge",
                "label": "Free — Edge TTS",
                "requires_key": False,
                "online": True,
                "disclosure": EDGE_DISCLOSURE,
            },
            {
                "id": "elevenlabs",
                "label": "ElevenLabs",
                "requires_key": True,
                "online": True,
                "configured": services.get_credential("elevenlabs") is not None,
                "disclosure": (
                    "Uses your ElevenLabs API key and your ElevenLabs credits. Text is sent to "
                    "ElevenLabs."
                ),
            },
        ],
        "limits": {
            "rate": list(edge_tts_client.RATE_RANGE),
            "pitch": list(edge_tts_client.PITCH_RANGE),
            "volume": list(edge_tts_client.VOLUME_RANGE),
            "preview_max_chars": PREVIEW_MAX_CHARS,
        },
        "default_edge_voice": edge_tts_client.DEFAULT_VOICE,
    }


class NarrationSettingsView(APIView):
    def get(self, request: Request) -> Response:
        return Response(narration_payload())

    def put(self, request: Request) -> Response:
        body = validate(NarrationSettingsBody, request.data)
        app = AppSettings.load()
        app.narration_provider = body.provider
        if body.edge is not None:
            app.edge_voice = body.edge.voice
            app.edge_voice_label = body.edge.voice_label.strip()
            app.edge_rate = body.edge.rate
            app.edge_pitch = body.edge.pitch
            app.edge_volume = body.edge.volume
        app.save()
        return Response(narration_payload())


class EdgeVoicesView(APIView):
    """Voice list for the free provider. Cached on the server; needs internet the first time."""

    def get(self, request: Request) -> Response:
        refresh = request.query_params.get("refresh") in ("1", "true")
        try:
            voices = edge_tts_client.list_voices(refresh=refresh)
        except edge_tts_client.EdgeTTSError as exc:
            raise ApiError(str(exc), status_code=502, code="voices_unavailable") from exc
        return Response({"voices": voices, "count": len(voices)})


# --- Imported settings that need a decision -------------------------------------------------


class ImportConflictsView(APIView):
    def get(self, request: Request) -> Response:
        return Response({"choices": account_import.pending_choices_payload()})


class ImportConflictResolveView(APIView):
    def post(self, request: Request, choice_id: int) -> Response:
        body = validate(ChoiceBody, request.data)
        account_import.resolve_choice(choice_id, body.choice)
        return Response({"choices": account_import.pending_choices_payload()})
