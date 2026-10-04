from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet
from rest_framework.test import APIClient

from engine.llm import CompletionRequest, CompletionResult, LLMError


@pytest.fixture(autouse=True)
def _framefusion_settings(settings: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings.FRAMEFUSION_ENCRYPTION_KEYS = [Fernet.generate_key().decode()]
    settings.FRAMEFUSION_JOBS_EAGER = True
    settings.FRAMEFUSION_UPLOAD_DIR = tmp_path / "uploads"
    output = tmp_path / "generated"
    output.mkdir()
    for module in (
        "engine.paths",
        "studio.media",
        "studio.legacy",
        "studio.handlers",
        "tools.handlers",
    ):
        monkeypatch.setattr(f"{module}.GENERATED_DIR", output, raising=False)
    from engine.services import edge_tts_client
    from providers import services

    services._model_cache.clear()
    monkeypatch.setattr(edge_tts_client, "_voice_cache", None)


PUBLIC_IP = "93.184.216.34"


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """Install a scripted web: ``routes[url] = handler``; unknown URLs return 404.

    Routes match by prefix in insertion order, and DNS resolves to a public address
    unless ``dns[host]`` says otherwise, so nothing touches the network.
    """
    from engine.services.images import safe_fetch, sources
    from studio import images as studio_images

    state: dict[str, Any] = {"routes": {}, "requests": [], "dns": {}, "headers": []}

    def handle(request: httpx.Request) -> httpx.Response:
        state["requests"].append(str(request.url))
        state["headers"].append(dict(request.headers))
        url = str(request.url)
        for prefix, handler in state["routes"].items():
            if url.startswith(prefix):
                return handler(request)
        return httpx.Response(404)

    def resolve(host: str) -> list[str]:
        return state["dns"].get(host, [PUBLIC_IP])

    monkeypatch.setattr(safe_fetch, "TRANSPORT", httpx.MockTransport(handle))
    monkeypatch.setattr(safe_fetch, "resolve_host", resolve)
    monkeypatch.setattr(safe_fetch, "sleep", lambda _seconds: None)
    studio_images.clear_cache()
    sources.clear_caches()
    yield state


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    return tmp_path / "generated"


@pytest.fixture
def client(db: Any) -> APIClient:
    return APIClient()


@pytest.fixture
def csrf_client(db: Any) -> APIClient:
    """A client that enforces CSRF like a browser would."""
    return APIClient(enforce_csrf_checks=True)


@dataclass
class FakeProvider:
    """Scripted ChatProvider used in place of the real SDK clients."""

    provider_name: str = "openrouter"
    responses: list[CompletionResult | LLMError] = field(default_factory=list)
    requests: list[CompletionRequest] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def label(self) -> str:
        return self.provider_name.title()

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        item = self.responses.pop(0) if self.responses else CompletionResult(text="Done.")
        if isinstance(item, LLMError):
            raise item
        item.provider = item.provider or self.provider_name
        item.model = item.model or request.model
        return item


@dataclass
class FakeRegistry:
    fakes: dict[str, FakeProvider] = field(default_factory=dict)
    used_keys: dict[str, str] = field(default_factory=dict)

    def get(self, provider: str) -> FakeProvider:
        return self.fakes.setdefault(provider, FakeProvider(provider))


@pytest.fixture
def fake_providers(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeRegistry]:
    """Route every provider to a FakeProvider and record which keys were used."""
    registry = FakeRegistry()

    def build(provider: str, api_key: str) -> FakeProvider:
        registry.used_keys[provider] = api_key
        return registry.get(provider)

    monkeypatch.setattr("providers.services.build_client", build)
    yield registry


def configure_ai(
    provider: str = "openrouter",
    model: str = "openai/gpt-4o-mini",
    key: str = "sk-or-v1-0123456789abcdef0123",
) -> None:
    from providers import services
    from providers.models import AppSettings

    services.save_api_key(provider, key)
    app = AppSettings.load()
    app.default_provider = provider
    app.default_model = model
    app.save()
