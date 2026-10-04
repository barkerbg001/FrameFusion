"""Validated task, delegation and artifact schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

TaskStatus = Literal[
    "proposed",  # planned by the orchestrator, not started
    "active",  # a specialist or service is working on it
    "completed",  # produced output that has not been checked yet
    "verified",  # output passed its completion criteria
    "failed",
    "cancelled",
    "skipped",  # not needed for this production (e.g. research, silent narration)
    "invalidated",  # an upstream artifact changed; must run again
]
DONE_STATUSES: tuple[TaskStatus, ...] = ("verified", "skipped")
Stage = Literal["brief", "research", "script", "visuals", "narration", "music", "render", "qc"]
STAGES: tuple[Stage, ...] = (
    "brief",
    "research",
    "script",
    "visuals",
    "narration",
    "music",
    "render",
    "qc",
)
DEPENDS_ON: dict[str, tuple[str, ...]] = {
    "brief": (),
    "research": ("brief",),
    "script": ("brief", "research"),
    "visuals": ("script",),
    "narration": ("script",),
    "music": ("narration",),
    "render": ("visuals", "narration", "music"),
    "qc": ("render",),
}
STAGE_SPECIALIST: dict[str, str] = {
    "brief": "orchestrator",
    "research": "research",
    "script": "script",
    "visuals": "visual",
    "narration": "narration",
    "music": "music",
    "render": "renderer",
    "qc": "qc",
}
STAGE_LABELS: dict[str, str] = {
    "brief": "Creative brief",
    "research": "Research",
    "script": "Script and scenes",
    "visuals": "Images",
    "narration": "Narration",
    "music": "Music bed",
    "render": "Timeline render",
    "qc": "Quality check",
}


def downstream_of(stage: str) -> list[str]:
    """Every stage that (transitively) depends on ``stage``."""
    found: list[str] = []
    for candidate in STAGES:
        if candidate == stage:
            continue
        pending = list(DEPENDS_ON[candidate])
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current == stage:
                found.append(candidate)
                break
            if current not in seen:
                seen.add(current)
                pending.extend(DEPENDS_ON[current])
    return found


class TaskRecord(BaseModel):
    id: str
    project_id: str
    job_id: str | None = None
    stage: str
    specialist: str
    objective: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    expected_output: str = ""
    status: TaskStatus = "proposed"
    attempt: int = 0
    max_attempts: int = 2
    input_hash: str = ""
    output: dict[str, Any] | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    limitations: list[str] = Field(default_factory=list)


class DelegationRequest(BaseModel):
    """What the orchestrator hands a specialist. Never contains credentials."""

    specialist: Literal["research", "script", "visual", "ideas"]
    objective: str = Field(min_length=3, max_length=600)
    inputs: dict[str, Any] = Field(default_factory=dict)


# --- Artifacts -------------------------------------------------------------------------


class ProductionBrief(BaseModel):
    title: str = Field(min_length=2, max_length=90)
    objective: str = Field(min_length=3, max_length=400)
    audience: str = Field(default="general social audience", max_length=160)
    tone: str = Field(default="clear and engaging", max_length=120)
    format: Literal["narrated", "silent"] = "narrated"
    target_seconds: int = Field(default=40, ge=15, le=90)
    scene_count: int = Field(default=5, ge=3, le=8)
    needs_research: bool = False
    research_questions: list[str] = Field(default_factory=list, max_length=5)
    background_music: bool = False
    visual_style: str = Field(default="real photographs, natural light", max_length=200)
    assumptions: list[str] = Field(default_factory=list, max_length=6)


class Scene(BaseModel):
    index: int = Field(ge=0)
    narration: str = Field(min_length=3, max_length=400)
    on_screen_text: str = Field(default="", max_length=90)
    visual_description: str = Field(min_length=3, max_length=300)
    image_query: str = Field(min_length=2, max_length=80)
    duration_seconds: float = Field(default=6.0, ge=2.0, le=20.0)


class ScriptArtifact(BaseModel):
    title: str = Field(min_length=2, max_length=90)
    hook: str = Field(min_length=3, max_length=200)
    scenes: list[Scene] = Field(min_length=3, max_length=10)
    caption: str = Field(default="", max_length=400)
    hashtags: list[str] = Field(default_factory=list, max_length=8)
    sources: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def renumber(self) -> ScriptArtifact:
        for position, scene in enumerate(self.scenes):
            scene.index = position
        return self

    @property
    def narration_text(self) -> str:
        return " ".join(scene.narration.strip() for scene in self.scenes)


SceneVisualStatus = Literal[
    "searching",
    "candidates_found",
    "awaiting_review",
    "selected",
    "no_suitable_result",
    "download_failed",
    "title_card",
]
# What the user can do next for an unresolved scene (shown as actions in the Scenes tab).
GapAction = Literal[
    "search_other_source",
    "refine_brief",
    "upload",
    "paste_url",
    "choose_illustrative",
    "title_card",
]


class SceneAsset(BaseModel):
    scene_index: int = Field(ge=0)
    asset_id: str
    candidate_id: str = ""
    reason: str = ""
    # "auto" only appears in projects produced before relevance checks existed.
    selected_by: Literal["visual", "auto", "user"] = "visual"
    verification: Literal["vision", "metadata", "user", "none"] = "none"
    rights_status: Literal["documented", "unknown"] = "documented"
    illustrative: bool = False


class SceneGap(BaseModel):
    scene_index: int
    reason: str
    missing: str = ""
    actions: list[GapAction] = Field(default_factory=list)


class SceneVisual(BaseModel):
    """Per-scene search record: brief, searches, assessed alternatives and outcome."""

    scene_index: int = Field(ge=0)
    status: SceneVisualStatus = "searching"
    brief: dict[str, Any] = Field(default_factory=dict)
    searches: list[dict[str, Any]] = Field(default_factory=list)
    # Browser-safe candidate summaries with their assessment; ``candidate`` holds the full
    # server-side record so the user can download by candidate_id later.
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    assessment: dict[str, Any] | None = None
    note: str = ""


class VisualResult(BaseModel):
    scene_assets: list[SceneAsset] = Field(default_factory=list)
    gaps: list[SceneGap] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    notes: str = ""
    scenes: list[SceneVisual] = Field(default_factory=list)

    def asset_for(self, scene_index: int) -> SceneAsset | None:
        return next((item for item in self.scene_assets if item.scene_index == scene_index), None)

    def scene_state(self, scene_index: int) -> SceneVisual | None:
        return next((item for item in self.scenes if item.scene_index == scene_index), None)


class NarrationArtifact(BaseModel):
    asset_id: str
    provider: str
    voice: str
    duration_seconds: float
    words: list[tuple[float, float, str]] = Field(default_factory=list)
    scene_durations: list[float] = Field(default_factory=list)


class RenderArtifact(BaseModel):
    asset_id: str
    file_name: str
    duration_seconds: float
    scene_count: int
    placeholder_scenes: list[int] = Field(default_factory=list)


class QCReport(BaseModel):
    passed: bool
    checks: list[dict[str, Any]] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)


class ProductionRequest(BaseModel):
    task: str = Field(min_length=3, max_length=4000)
    context: str = Field(default="", max_length=8000)
    short_format: Literal["auto", "narrated", "silent"] = "auto"
    render_video: bool = True
    stop_after: Stage | None = None
    from_stage: Stage | None = None
    user_urls: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("short_format", mode="before")
    @classmethod
    def legacy_formats(cls, value: Any) -> Any:
        # Older clients sent the renderer names.
        return {"sound_short": "narrated", "text_short": "silent", "sound": "narrated"}.get(
            value, value
        )
