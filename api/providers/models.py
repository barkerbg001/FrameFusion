"""Application-level configuration for the single-user FrameFusion install.

There are no accounts: one ``AppSettings`` row holds preferences, and each service
has at most one encrypted credential.
"""

from __future__ import annotations

from django.db import models


class Provider(models.TextChoices):
    """AI model providers the orchestrator and specialists can route to."""

    OPENROUTER = "openrouter", "OpenRouter"
    GEMINI = "gemini", "Google Gemini"
    ANTHROPIC = "anthropic", "Anthropic Claude"


class MediaService(models.TextChoices):
    """Optional media integrations used by the rendering pipeline."""

    ELEVENLABS = "elevenlabs", "ElevenLabs"
    PEXELS = "pexels", "Pexels"
    PIXABAY = "pixabay", "Pixabay"
    BRAVE = "brave", "Brave Search"


SERVICE_CHOICES = [*Provider.choices, *MediaService.choices]


class ModelRoute(models.TextChoices):
    """Which agents share a provider/model. Unrelated to the orchestrator's personality."""

    PLANNER = "planner", "Orchestrator and writing"
    PRODUCTION = "production", "Visual specialist"


class OrchestratorPersonality(models.TextChoices):
    DIRECTOR = "director", "Director"
    CREATIVE_PARTNER = "creative_partner", "Creative Partner"


class Theme(models.TextChoices):
    SYSTEM = "system", "System"
    DARK = "dark", "Dark"
    LIGHT = "light", "Light"


class ProviderCredential(models.Model):
    """One API key per service, encrypted with FRAMEFUSION_ENCRYPTION_KEY."""

    class TestStatus(models.TextChoices):
        UNTESTED = "untested", "Not tested"
        VALID = "valid", "Valid"
        FAILED = "failed", "Failed"

    provider = models.CharField(max_length=20, choices=SERVICE_CHOICES, unique=True)
    encrypted_key = models.TextField()
    key_hint = models.CharField(max_length=8, blank=True)
    last_test_status = models.CharField(
        max_length=10, choices=TestStatus.choices, default=TestStatus.UNTESTED
    )
    last_test_message = models.CharField(max_length=500, blank=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.get_provider_display()} key"


class NarrationProvider(models.TextChoices):
    EDGE = "edge", "Free — Edge TTS"
    ELEVENLABS = "elevenlabs", "ElevenLabs"


class AppSettings(models.Model):
    """Singleton (pk=1) holding every preference for this install."""

    ONBOARDING_STEPS = (
        "welcome",
        "providers",
        "models",
        "narration",
        "media",
        "appearance",
        "review",
    )

    # AI routing
    default_provider = models.CharField(max_length=20, choices=Provider.choices, blank=True)
    default_model = models.CharField(max_length=200, blank=True)
    temperature = models.FloatField(null=True, blank=True)
    max_output_tokens = models.PositiveIntegerField(null=True, blank=True)

    # Appearance
    theme = models.CharField(max_length=10, choices=Theme.choices, default=Theme.SYSTEM)

    # How the single orchestrator talks; projects may override it.
    orchestrator_personality = models.CharField(
        max_length=20,
        choices=OrchestratorPersonality.choices,
        default=OrchestratorPersonality.DIRECTOR,
        db_default=OrchestratorPersonality.DIRECTOR,
    )

    # Narration (text-to-speech). Music and sound effects are configured separately.
    narration_provider = models.CharField(
        max_length=12,
        choices=NarrationProvider.choices,
        default=NarrationProvider.EDGE,
        db_default=NarrationProvider.EDGE,
    )
    edge_voice = models.CharField(
        max_length=80,
        default="en-US-EmmaMultilingualNeural",
        db_default="en-US-EmmaMultilingualNeural",
    )
    edge_voice_label = models.CharField(max_length=160, blank=True, db_default="")
    edge_rate = models.SmallIntegerField(default=0, db_default=0)  # percent, -50..100
    edge_pitch = models.SmallIntegerField(default=0, db_default=0)  # Hz, -50..50
    edge_volume = models.SmallIntegerField(default=0, db_default=0)  # percent, -50..50

    # ElevenLabs narration and music
    elevenlabs_voice_id = models.CharField(max_length=64, blank=True)
    elevenlabs_voice_name = models.CharField(max_length=120, blank=True)
    elevenlabs_model_id = models.CharField(max_length=64, default="eleven_multilingual_v2")
    elevenlabs_stability = models.FloatField(null=True, blank=True)
    elevenlabs_similarity_boost = models.FloatField(null=True, blank=True)
    elevenlabs_style = models.FloatField(null=True, blank=True)
    elevenlabs_speed = models.FloatField(null=True, blank=True)
    elevenlabs_speaker_boost = models.BooleanField(null=True, blank=True)
    elevenlabs_music_model = models.CharField(max_length=32, default="music_v2")

    # Pexels stock media defaults
    pexels_media_type = models.CharField(max_length=10, default="video")
    pexels_orientation = models.CharField(max_length=10, default="portrait", blank=True)
    pexels_size = models.CharField(max_length=10, blank=True)

    # Onboarding progress
    onboarding_step = models.CharField(max_length=20, default="welcome")
    onboarding_skipped = models.JSONField(default=list, blank=True)
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "app settings"
        verbose_name_plural = "app settings"

    def __str__(self) -> str:
        return "FrameFusion settings"

    def save(self, *args: object, **kwargs: object) -> None:
        self.pk = 1
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    @classmethod
    def load(cls) -> AppSettings:
        settings, _ = cls.objects.get_or_create(pk=1)
        return settings


class AgentModelOverride(models.Model):
    # Named ``persona`` for compatibility with older databases; it holds a model route.
    persona = models.CharField(max_length=20, choices=ModelRoute.choices, unique=True)
    provider = models.CharField(max_length=20, choices=Provider.choices)
    model = models.CharField(max_length=200)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.persona} → {self.provider}:{self.model}"


class ImportedSettingChoice(models.Model):
    """A setting that differed between accounts in an imported multi-user database.

    Nothing is applied until someone picks a candidate (or keeps the current value)
    in Settings → Data or with ``manage.py resolve_import_conflicts``. Candidate
    payloads may contain still-encrypted API keys; they are never sent to the browser
    and are cleared once the choice is resolved.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RESOLVED = "resolved", "Resolved"

    group = models.CharField(max_length=40)
    label = models.CharField(max_length=120)
    candidates = models.JSONField(default=list)
    current_summary = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    resolution = models.CharField(max_length=80, blank=True)
    source = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["group"],
                condition=models.Q(status="pending"),
                name="unique_pending_import_choice",
            )
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.status})"
