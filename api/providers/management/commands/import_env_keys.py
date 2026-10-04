"""Move API keys from api/.env into the encrypted credential store.

Existing saved keys are kept unless --replace is given. After importing, delete the
keys from api/.env; the running app never reads them from there.
"""

import os
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from providers import services
from providers.crypto import encryption_configured
from providers.models import AppSettings

ENV_KEYS = {
    "openrouter": ("OPENROUTER_API_KEY", "OPEN_ROUTER_API_KEY"),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "elevenlabs": ("ELEVENLABS_API_KEY",),
    "pexels": ("PEXELS_API_KEY",),
}
ENV_MODELS = {
    "openrouter": ("OPENROUTER_MODEL", "OPEN_ROUTER_MODEL"),
    "gemini": ("GEMINI_MODEL",),
    "anthropic": ("ANTHROPIC_MODEL",),
}


def _first_env(names: tuple[str, ...]) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


class Command(BaseCommand):
    help = "Import OpenRouter, Gemini, Anthropic, ElevenLabs and Pexels keys from the environment."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--replace", action="store_true", help="Overwrite keys that are already saved."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not encryption_configured():
            raise CommandError("FRAMEFUSION_ENCRYPTION_KEY is not set or invalid.")

        imported: list[str] = []
        for service, names in ENV_KEYS.items():
            value = _first_env(names)
            label = services.provider_label(service)
            if not value:
                continue
            if services.get_credential(service) and not options["replace"]:
                self.stdout.write(f"Skipped {label}: a key is already saved (use --replace).")
                continue
            services.save_api_key(service, value)
            imported.append(service)
            self.stdout.write(self.style.SUCCESS(f"Imported {label} key."))

        app = AppSettings.load()
        ai_imported = [s for s in imported if s in ENV_MODELS]
        if ai_imported and not app.default_provider:
            provider = ai_imported[0]
            fallback = services.fallback_models(provider)
            model = _first_env(ENV_MODELS[provider]) or (fallback[0].id if fallback else "")
            app.default_provider = provider
            app.default_model = model
            app.save(update_fields=["default_provider", "default_model", "updated_at"])
            self.stdout.write(
                f"Default provider set to {services.provider_label(provider)} ({model})."
            )
        voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
        if voice_id.isalnum() and not app.elevenlabs_voice_id:
            app.elevenlabs_voice_id = voice_id
            app.save(update_fields=["elevenlabs_voice_id", "updated_at"])
            self.stdout.write("ElevenLabs voice set from ELEVENLABS_VOICE_ID.")
        if not imported:
            self.stdout.write("No new keys imported.")
