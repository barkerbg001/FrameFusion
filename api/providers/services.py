"""Saved credentials, model discovery and LLM routing for the single local workspace.

Routing is explicit: each model route ("planner" for the orchestrator and writing
specialists, "production" for the visual specialist) uses its override if set,
otherwise the default provider/model. Routes are independent of the
orchestrator's personality. If that provider has no saved key the call fails with a message
pointing to Settings; it never falls back to another provider.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from engine.llm import (
    ROUTE_LABELS,
    LLMBinding,
    LLMConfigurationError,
    LLMError,
    Resolver,
    Route,
    route_for,
)

from .clients import CLIENTS, ConnectionResult, ModelInfo, ProviderClient, ProviderInfo
from .clients.media import MEDIA_CLIENTS, MediaServiceClient
from .crypto import decrypt_secret, encrypt_secret, key_hint
from .models import (
    SERVICE_CHOICES,
    AgentModelOverride,
    AppSettings,
    MediaService,
    ProviderCredential,
)

SERVICE_LABELS = dict(SERVICE_CHOICES)
ROUTES: tuple[Route, ...] = ("planner", "production")
MEDIA_SERVICES = tuple(MediaService.values)

MEDIA_FEATURES = {
    "elevenlabs": "Premium narration voices and AI-composed music",
    "pexels": "Stock photo and video search and footage-based renders",
    "pixabay": "Licensed stock photos, illustrations and vector graphics for scenes",
    "brave": "Web image discovery when stock sources have nothing (rights unknown, you review)",
}


def provider_label(provider: str) -> str:
    return SERVICE_LABELS.get(provider, provider)


def service_kind(service: str) -> str:
    return "ai" if service in CLIENTS else "media"


def service_info(service: str) -> ProviderInfo:
    if service in CLIENTS:
        return CLIENTS[service].info
    return MEDIA_CLIENTS[service].info


def build_client(provider: str, api_key: str) -> ProviderClient:
    try:
        client_class = CLIENTS[provider]
    except KeyError as exc:
        raise LLMError(f"Unknown provider: {provider}", kind="unsupported") from exc
    return client_class(
        api_key,
        timeout=settings.FRAMEFUSION_LLM_TIMEOUT_SECONDS,
        max_retries=settings.FRAMEFUSION_LLM_MAX_RETRIES,
    )


def discovery_client(provider: str, api_key: str) -> ProviderClient:
    client_class = CLIENTS[provider]
    return client_class(
        api_key, timeout=settings.FRAMEFUSION_DISCOVERY_TIMEOUT_SECONDS, max_retries=1
    )


def media_client(service: str, api_key: str) -> MediaServiceClient:
    return MEDIA_CLIENTS[service](api_key, timeout=settings.FRAMEFUSION_DISCOVERY_TIMEOUT_SECONDS)


def test_connection(service: str, api_key: str) -> ConnectionResult:
    if service in CLIENTS:
        return discovery_client(service, api_key).test_connection()
    return media_client(service, api_key).test_connection()


def get_credential(service: str) -> ProviderCredential | None:
    return ProviderCredential.objects.filter(provider=service).first()


def configured_services() -> set[str]:
    return set(ProviderCredential.objects.values_list("provider", flat=True))


def get_api_key(service: str) -> str:
    credential = get_credential(service)
    if credential is None:
        section = (
            "AI providers"
            if service_kind(service) == "ai"
            else "Narration"
            if service == "elevenlabs"
            else "Stock media"
        )
        raise LLMConfigurationError(
            f"No {provider_label(service)} API key is saved. Add one in Settings → {section}.",
            provider=service,
        )
    return decrypt_secret(credential.encrypted_key)


def save_api_key(service: str, api_key: str) -> ProviderCredential:
    encrypted = encrypt_secret(api_key)
    with transaction.atomic():
        credential, _ = ProviderCredential.objects.update_or_create(
            provider=service,
            defaults={
                "encrypted_key": encrypted,
                "key_hint": key_hint(api_key),
                "last_test_status": ProviderCredential.TestStatus.UNTESTED,
                "last_test_message": "",
                "last_tested_at": None,
            },
        )
    invalidate_models(service)
    return credential


def delete_api_key(service: str) -> bool:
    deleted, _ = ProviderCredential.objects.filter(provider=service).delete()
    invalidate_models(service)
    return bool(deleted)


def record_test(credential: ProviderCredential, result: ConnectionResult) -> None:
    credential.last_test_status = (
        ProviderCredential.TestStatus.VALID if result.ok else ProviderCredential.TestStatus.FAILED
    )
    credential.last_test_message = result.message[:500]
    credential.last_tested_at = timezone.now()
    credential.save(update_fields=["last_test_status", "last_test_message", "last_tested_at"])


def credential_payload(service: str, credential: ProviderCredential | None) -> dict[str, Any]:
    info = service_info(service)
    payload: dict[str, Any] = {
        "provider": service,
        "kind": service_kind(service),
        "label": info.label,
        "key_url": info.key_url,
        "docs_url": info.docs_url,
        "key_prefix_hint": info.key_prefix_hint,
        "test_billing_note": info.test_billing_note,
        "capabilities": info.capabilities,
        "features": MEDIA_FEATURES.get(service, "Planning, writing and production agents"),
        "configured": credential is not None,
        "masked_key": None,
        "status": "unconfigured",
        "last_test_message": "",
        "last_tested_at": None,
        "updated_at": None,
    }
    if credential is not None:
        payload.update(
            masked_key=f"••••{credential.key_hint}" if credential.key_hint else "••••",
            status={
                "valid": "valid",
                "failed": "failed",
            }.get(credential.last_test_status, "configured"),
            last_test_message=credential.last_test_message,
            last_tested_at=(
                credential.last_tested_at.isoformat() if credential.last_tested_at else None
            ),
            updated_at=credential.updated_at.isoformat(),
        )
    return payload


def all_credentials_payload() -> list[dict[str, Any]]:
    credentials = {c.provider: c for c in ProviderCredential.objects.all()}
    return [credential_payload(name, credentials.get(name)) for name in [*CLIENTS, *MEDIA_CLIENTS]]


# --- Engine integration lookups -----------------------------------------------------------


def integration_key(service: str) -> str | None:
    credential = get_credential(service)
    if credential is None:
        return None
    return decrypt_secret(credential.encrypted_key)


def integration_configured(service: str) -> bool:
    return ProviderCredential.objects.filter(provider=service).exists()


def media_settings_payload(app: AppSettings | None = None) -> dict[str, dict[str, Any]]:
    app = app or AppSettings.load()
    return {
        "elevenlabs": {
            "voice_id": app.elevenlabs_voice_id,
            "voice_name": app.elevenlabs_voice_name,
            "model_id": app.elevenlabs_model_id,
            "music_model": app.elevenlabs_music_model,
            "voice_settings": {
                "stability": app.elevenlabs_stability,
                "similarity_boost": app.elevenlabs_similarity_boost,
                "style": app.elevenlabs_style,
                "speed": app.elevenlabs_speed,
                "use_speaker_boost": app.elevenlabs_speaker_boost,
            },
        },
        "pexels": {
            "media_type": app.pexels_media_type,
            "orientation": app.pexels_orientation,
            "size": app.pexels_size,
        },
    }


def narration_settings_payload(app: AppSettings | None = None) -> dict[str, Any]:
    app = app or AppSettings.load()
    return {
        "provider": app.narration_provider,
        "edge": {
            "voice": app.edge_voice,
            "voice_label": app.edge_voice_label,
            "rate": app.edge_rate,
            "pitch": app.edge_pitch,
            "volume": app.edge_volume,
        },
        "elevenlabs": {
            "voice_id": app.elevenlabs_voice_id,
            "voice_name": app.elevenlabs_voice_name,
            "model_id": app.elevenlabs_model_id,
        },
    }


def integration_settings(service: str) -> dict[str, Any]:
    if service == "narration":
        return narration_settings_payload()
    return media_settings_payload().get(service, {})


# --- Model catalog -----------------------------------------------------------------------

_CACHE_TTL_SECONDS = 600
_model_cache: dict[str, tuple[float, list[ModelInfo]]] = {}
_cache_lock = threading.Lock()


def invalidate_models(provider: str) -> None:
    with _cache_lock:
        _model_cache.pop(provider, None)


def fallback_models(provider: str) -> list[ModelInfo]:
    return [
        ModelInfo(id=model_id, label=model_id, source="fallback")
        for model_id in settings.FRAMEFUSION_FALLBACK_MODELS.get(provider, [])
    ]


def list_models(provider: str, *, refresh: bool = False) -> dict[str, Any]:
    if not refresh:
        with _cache_lock:
            cached = _model_cache.get(provider)
        if cached and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
            return {"source": "live", "models": [m.to_dict() for m in cached[1]], "error": None}

    credential = get_credential(provider)
    if credential is None:
        return {
            "source": "fallback",
            "models": [m.to_dict() for m in fallback_models(provider)],
            "error": "Add an API key to load the live model list.",
        }
    try:
        api_key = decrypt_secret(credential.encrypted_key)
        models = discovery_client(provider, api_key).list_models()
    except LLMError as exc:
        return {
            "source": "fallback",
            "models": [m.to_dict() for m in fallback_models(provider)],
            "error": exc.message,
        }
    with _cache_lock:
        _model_cache[provider] = (time.monotonic(), models)
    return {"source": "live", "models": [m.to_dict() for m in models], "error": None}


# --- Routing -----------------------------------------------------------------------------


@dataclass
class ModelRoute:
    route: Route
    provider: str
    model: str
    source: str  # "override" | "default" | "none"


def model_routes() -> dict[Route, ModelRoute]:
    app = AppSettings.load()
    # The DB column is still called ``persona`` for compatibility with older databases.
    overrides = {o.persona: o for o in AgentModelOverride.objects.all()}
    routes: dict[Route, ModelRoute] = {}
    for route in ROUTES:
        override = overrides.get(route)
        if override is not None:
            routes[route] = ModelRoute(route, override.provider, override.model, "override")
        elif app.default_provider:
            routes[route] = ModelRoute(route, app.default_provider, app.default_model, "default")
        else:
            routes[route] = ModelRoute(route, "", "", "none")
    return routes


def readiness() -> dict[str, dict[str, Any]]:
    configured = configured_services()
    result: dict[str, dict[str, Any]] = {}
    for key, route in model_routes().items():
        name = ROUTE_LABELS[key]
        problem = None
        if not route.provider:
            problem = f"Choose a default AI provider and model for the {name.lower()} route."
        elif route.provider not in configured:
            problem = (
                f"The {name.lower()} route uses {provider_label(route.provider)}, but no "
                f"{provider_label(route.provider)} API key is saved."
            )
        elif not route.model:
            problem = (
                f"Choose a {provider_label(route.provider)} model for the {name.lower()} route."
            )
        result[key] = {
            "route": key,
            "name": name,
            "provider": route.provider or None,
            "provider_label": provider_label(route.provider) if route.provider else None,
            "model": route.model or None,
            "source": route.source,
            "ready": problem is None,
            "problem": problem,
        }
    return result


def integrations_status() -> dict[str, dict[str, Any]]:
    configured = configured_services()
    return {
        service: {
            "service": service,
            "label": provider_label(service),
            "configured": service in configured,
            "features": MEDIA_FEATURES[service],
        }
        for service in MEDIA_SERVICES
    }


def make_resolver() -> Resolver:
    """Snapshot the routing and return a resolver for engine.llm.

    Credentials are decrypted lazily, once per provider, the first time an agent
    using that provider runs.
    """
    routes = model_routes()
    app = AppSettings.load()
    clients: dict[str, ProviderClient] = {}
    lock = threading.Lock()

    def resolve(agent_id: str) -> LLMBinding:
        key = route_for(agent_id)
        route = routes[key]
        name = f"The {ROUTE_LABELS[key].lower()} route"
        if not route.provider:
            raise LLMConfigurationError(
                f"{name} has no AI provider configured. Open Settings → AI providers, add an "
                "API key, and choose a default model."
            )
        if not route.model:
            raise LLMConfigurationError(
                f"{name} has no {provider_label(route.provider)} model selected. Choose one in "
                "Settings → AI providers.",
                provider=route.provider,
            )
        with lock:
            client = clients.get(route.provider)
            if client is None:
                try:
                    api_key = get_api_key(route.provider)
                except LLMConfigurationError as exc:
                    if exc.kind == "not_configured":
                        raise LLMConfigurationError(
                            f"{name} uses {provider_label(route.provider)}, but no "
                            f"{provider_label(route.provider)} API key is saved. Add one in "
                            "Settings → AI providers or pick a different provider for it.",
                            provider=route.provider,
                        ) from None
                    raise
                client = build_client(route.provider, api_key)
                clients[route.provider] = client
        return LLMBinding(
            provider=client,
            model=route.model,
            route=key,
            temperature=app.temperature,
            max_output_tokens=app.max_output_tokens,
        )

    return resolve
