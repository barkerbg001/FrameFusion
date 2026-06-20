from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.video_editor import VideoEditorReport


class ProductionRequest(BaseModel):
    task: str = Field(..., min_length=5, max_length=3000)
    context: Optional[str] = Field(None, max_length=2000)
    render_video: bool = Field(
        True,
        description="When true, the Editor agent renders an MP4 at the end",
    )
    short_format: Literal["auto", "sound", "silent"] = "auto"


class AgentAssignment(BaseModel):
    agent_id: str
    objective: str
    priority: Literal["required", "recommended", "optional"] = "required"


class DirectorBrief(BaseModel):
    creative_vision: str
    tone: str
    target_audience: str
    assignments: List[AgentAssignment]
    approval_notes: List[str] = Field(default_factory=list)


class WorkflowPhase(BaseModel):
    name: str
    agent_id: str
    deadline_note: str
    deliverables: List[str]


class AssetTrackerItem(BaseModel):
    asset_type: str
    description: str
    status: Literal["planned", "in_progress", "ready"] = "planned"
    owner_agent: str


class WorkflowPlan(BaseModel):
    summary: str
    phases: List[WorkflowPhase]
    assets: List[AssetTrackerItem]
    risks: List[str] = Field(default_factory=list)


class ShotItem(BaseModel):
    shot_number: int
    description: str
    framing: str
    camera_movement: str
    duration_seconds: float
    notes: str = ""


class CinematographyReport(BaseModel):
    shot_list: List[ShotItem]
    composition_notes: List[str]
    pacing_notes: str
    limitations: List[str] = Field(default_factory=list)


class VisualAsset(BaseModel):
    asset_type: Literal["b_roll", "background", "graphic", "character"]
    description: str
    source: Literal["pexels", "generated", "text_overlay", "existing"]
    search_query: str = ""


class VisualReport(BaseModel):
    visual_style: str
    color_palette: List[str]
    assets: List[VisualAsset]
    limitations: List[str] = Field(default_factory=list)


class VoiceReport(BaseModel):
    narration_approach: str
    voice_style: str
    delivery_notes: List[str]
    pacing: str
    elevenlabs_notes: str = ""
    limitations: List[str] = Field(default_factory=list)


class MusicSceneCue(BaseModel):
    scene_label: str
    mood: str
    genre: str
    tempo: str
    music_prompt: str
    duration_seconds: int
    transition_note: str = ""


class MusicDirectorReport(BaseModel):
    overall_style: str
    scene_cues: List[MusicSceneCue]
    transition_strategy: str
    limitations: List[str] = Field(default_factory=list)


class SoundLayer(BaseModel):
    layer_type: Literal["sfx", "ambient", "foley", "mix_note"]
    description: str
    timing: str
    intensity: Literal["subtle", "medium", "prominent"] = "subtle"


class SoundDesignReport(BaseModel):
    ambient_bed: str
    layers: List[SoundLayer]
    mix_suggestions: List[str]
    limitations: List[str] = Field(default_factory=list)


class ProductionReport(BaseModel):
    task: str
    produced_at: str
    pipeline: List[str]
    director: DirectorBrief
    workflow: WorkflowPlan
    research: Dict[str, Any]
    script: Dict[str, Any]
    cinematography: CinematographyReport
    visual: VisualReport
    voice: VoiceReport
    music_director: MusicDirectorReport
    sound_design: SoundDesignReport
    editor: Optional[VideoEditorReport] = None
    limitations: List[str] = Field(default_factory=list)


class AgentTaskRequest(BaseModel):
    task: str = Field(..., min_length=5, max_length=3000)
    context: Optional[str] = Field(None, max_length=2000)


class CinematographyRequest(AgentTaskRequest):
    research: Optional[Dict[str, Any]] = None
    script: Optional[Dict[str, Any]] = None


class VisualRequest(AgentTaskRequest):
    research: Optional[Dict[str, Any]] = None
    cinematography: Optional[Dict[str, Any]] = None


class VoiceRequest(AgentTaskRequest):
    script: Optional[Dict[str, Any]] = None
    short_format: Literal["auto", "sound", "silent"] = "auto"


class MusicDirectorRequest(AgentTaskRequest):
    script: Optional[Dict[str, Any]] = None
    cinematography: Optional[Dict[str, Any]] = None


class SoundDesignRequest(AgentTaskRequest):
    cinematography: Optional[Dict[str, Any]] = None
    music_director: Optional[Dict[str, Any]] = None


class WorkflowRequest(AgentTaskRequest):
    director_brief: Optional[Dict[str, Any]] = None
