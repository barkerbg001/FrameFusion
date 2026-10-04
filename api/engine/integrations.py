"""Saved media-service credentials and preferences, as seen by engine code.

The engine has no Django imports. The providers app registers lookups at startup
(see ``providers.apps``) that read the encrypted keys and ``AppSettings`` from
SQLite; keys are only decrypted at the moment a service call needs them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

Service = Literal["elevenlabs", "pexels"]

SERVICE_LABELS: dict[str, str] = {"elevenlabs": "ElevenLabs", "pexels": "Pexels"}
ELEVENLABS_HINT = "Add an ElevenLabs API key in Settings → Narration"
SETUP_HINT: dict[str, str] = {
    "elevenlabs": "Add an ElevenLabs API key in Settings → Narration for ElevenLabs voices "
    "and AI music.",
    "pexels": "Add a Pexels API key in Settings → Stock media for stock footage.",
}

KeyLookup = Callable[[str], str | None]
ConfiguredLookup = Callable[[str], bool]
SettingsLookup = Callable[[str], dict[str, Any]]

_key_lookup: KeyLookup | None = None
_configured_lookup: ConfiguredLookup | None = None
_settings_lookup: SettingsLookup | None = None


class IntegrationNotConfigured(Exception):
    def __init__(self, service: str) -> None:
        self.service = service
        label = SERVICE_LABELS.get(service, service)
        super().__init__(f"{label} is not set up. {SETUP_HINT.get(service, '')}".strip())


def register(
    key_lookup: KeyLookup, configured_lookup: ConfiguredLookup, settings_lookup: SettingsLookup
) -> None:
    global _key_lookup, _configured_lookup, _settings_lookup
    _key_lookup = key_lookup
    _configured_lookup = configured_lookup
    _settings_lookup = settings_lookup


def get_key(service: Service) -> str | None:
    if _key_lookup is None:
        return None
    return _key_lookup(service) or None


def require_key(service: Service) -> str:
    key = get_key(service)
    if not key:
        raise IntegrationNotConfigured(service)
    return key


def is_configured(service: Service) -> bool:
    if _configured_lookup is None:
        return False
    return _configured_lookup(service)


def get_settings(service: Service | Literal["narration"]) -> dict[str, Any]:
    if _settings_lookup is None:
        return {}
    return _settings_lookup(service)


def setup_hint(service: Service) -> str:
    return SETUP_HINT[service]
