import uuid

from django.db import models


class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=120, default="Untitled project")
    title_locked = models.BooleanField(default=False)
    legacy_id = models.CharField(max_length=64, blank=True, db_index=True)
    # Blank means "use the default from Settings → Narration".
    narration_provider = models.CharField(max_length=12, blank=True, db_default="")
    narration_voice = models.CharField(max_length=80, blank=True, db_default="")
    narration_voice_label = models.CharField(max_length=160, blank=True, db_default="")
    # Blank means "use the default orchestrator personality from Settings".
    personality = models.CharField(max_length=20, blank=True, db_default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["-updated_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["legacy_id"],
                condition=~models.Q(legacy_id=""),
                name="unique_legacy_project",
            )
        ]

    def __str__(self) -> str:
        return self.title


class GenerationJob(models.Model):
    class Kind(models.TextChoices):
        CHAT = "chat", "Conversation reply"
        PRODUCTION = "production", "Production pipeline"
        AGENT = "agent", "Single agent"
        RENDER = "render", "Render"
        NARRATION = "narration", "Narration"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    ACTIVE = (Status.QUEUED, Status.RUNNING)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="jobs", null=True, blank=True
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    agent = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    input = models.JSONField(default=dict)
    result = models.JSONField(null=True, blank=True)
    error = models.JSONField(null=True, blank=True)
    usage = models.JSONField(default=list)
    cancel_requested = models.BooleanField(default=False)
    retry_of = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="retries"
    )
    boot_id = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.kind} job {self.id} ({self.status})"

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE


class JobEvent(models.Model):
    job = models.ForeignKey(GenerationJob, on_delete=models.CASCADE, related_name="events")
    seq = models.PositiveIntegerField()
    type = models.CharField(max_length=30)
    agent = models.CharField(max_length=40, blank=True)
    # Orchestrator personality for orchestrator events; blank for specialists and services.
    persona = models.CharField(max_length=20, blank=True)
    message = models.CharField(max_length=500, blank=True)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["seq"]
        constraints = [models.UniqueConstraint(fields=["job", "seq"], name="unique_job_event_seq")]


class Message(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    # The orchestrator personality that wrote an assistant message.
    persona = models.CharField(max_length=20, blank=True)
    attachments = models.JSONField(default=list)
    job = models.ForeignKey(
        GenerationJob, on_delete=models.SET_NULL, null=True, blank=True, related_name="messages"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class MediaAsset(models.Model):
    class Kind(models.TextChoices):
        VIDEO = "video", "Video"
        AUDIO = "audio", "Audio"
        IMAGE = "image", "Image"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="media"
    )
    job = models.ForeignKey(
        GenerationJob, on_delete=models.SET_NULL, null=True, blank=True, related_name="media"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    file_name = models.CharField(max_length=255, unique=True)
    display_name = models.CharField(max_length=255)
    duration_seconds = models.FloatField(null=True, blank=True)
    size_bytes = models.BigIntegerField(default=0)
    # What the asset is for in a production: video, narration, music, scene image, upload.
    role = models.CharField(max_length=20, blank=True, db_default="")
    # Provenance for downloaded images. Text here came from third parties.
    provider = models.CharField(max_length=20, blank=True, db_default="")
    candidate_id = models.CharField(max_length=120, blank=True, db_default="")
    source_url = models.URLField(max_length=2048, blank=True, db_default="")
    source_page_url = models.URLField(max_length=2048, blank=True, db_default="")
    title = models.CharField(max_length=200, blank=True, db_default="")
    creator = models.CharField(max_length=200, blank=True, db_default="")
    creator_url = models.URLField(max_length=2048, blank=True, db_default="")
    license = models.CharField(max_length=80, blank=True, db_default="")
    license_url = models.URLField(max_length=2048, blank=True, db_default="")
    attribution = models.CharField(max_length=500, blank=True, db_default="")
    rights_status = models.CharField(max_length=12, blank=True, db_default="")
    user_supplied = models.BooleanField(default=False, db_default=False)
    checksum = models.CharField(max_length=64, blank=True, db_default="", db_index=True)
    mime = models.CharField(max_length=40, blank=True, db_default="")
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True, db_default={})
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["-created_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "checksum"],
                condition=~models.Q(checksum=""),
                name="unique_project_checksum",
            )
        ]

    def __str__(self) -> str:
        return self.display_name


class ProductionTask(models.Model):
    """One unit of delegated work in a production, persisted so runs can resume."""

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        VERIFIED = "verified", "Verified"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        SKIPPED = "skipped", "Skipped"
        INVALIDATED = "invalidated", "Invalidated"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    job = models.ForeignKey(
        GenerationJob, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
    )
    stage = models.CharField(max_length=20)
    specialist = models.CharField(max_length=20)
    objective = models.CharField(max_length=600, blank=True)
    inputs = models.JSONField(default=dict, blank=True)
    depends_on = models.JSONField(default=list, blank=True)
    expected_output = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PROPOSED)
    attempt = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=2)
    input_hash = models.CharField(max_length=64, blank=True)
    output = models.JSONField(null=True, blank=True)
    artifact_ids = models.JSONField(default=list, blank=True)
    error = models.JSONField(null=True, blank=True)
    limitations = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["project", "stage", "-created_at"])]
        constraints = [
            # At most one task per stage can be running in a project at a time.
            models.UniqueConstraint(
                fields=["project", "stage"],
                condition=models.Q(status="active"),
                name="one_active_task_per_stage",
            )
        ]

    def __str__(self) -> str:
        return f"{self.stage} ({self.status})"
