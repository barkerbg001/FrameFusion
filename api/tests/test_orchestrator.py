"""The orchestrator, its personalities and the persisted production run.

Specialists, narration and the renderer are replaced with scripted fakes, so
these tests exercise task bookkeeping (reuse, invalidation, cancel, retry) and
the API around it without any model, network or ffmpeg call.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from rest_framework.test import APIClient

from engine.orchestrator import chat, production, specialists
from engine.orchestrator.personalities import PERSONALITIES, personality_block
from engine.orchestrator.production import ProductionStageError, run_production
from engine.orchestrator.schemas import (
    ProductionBrief,
    ProductionRequest,
    SceneAsset,
    ScriptArtifact,
    VisualResult,
    downstream_of,
)
from engine.runtime import RunCancelled, run_context
from engine.services import narration
from engine.services.images.candidates import ImageCandidate, validate_image
from engine.services.timeline import RenderOutcome
from studio.models import GenerationJob, MediaAsset, ProductionTask, Project
from studio.store import DjangoProjectStore, replace_scene_asset

from .conftest import FakeRegistry, configure_ai

pytestmark = pytest.mark.django_db

KEY = "sk-or-v1-0123456789abcdef0123"  # gitleaks:allow (dummy)
SCENES = 3


def _jpeg(color: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (720, 1280), color).save(buffer, format="JPEG")
    return buffer.getvalue()


@dataclass
class Studio:
    """Scripted specialists and services; ``calls`` counts real (non-reused) work."""

    calls: dict[str, int] = field(default_factory=dict)
    narration_error: Exception | None = None
    visuals_error: BaseException | None = None
    qc_passes: bool = True
    rights: str = "documented"
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def count(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1


@pytest.fixture
def studio(monkeypatch: pytest.MonkeyPatch, output_dir: Path) -> Studio:
    state = Studio()

    def run_brief(request: ProductionRequest) -> ProductionBrief:
        state.count("brief")
        return ProductionBrief(
            title="Tide pools",
            objective=request.task,
            format="silent" if request.short_format == "silent" else "narrated",
            scene_count=SCENES,
        )

    def run_script(
        brief: ProductionBrief, research: Any, feedback: list[str] | None = None
    ) -> ScriptArtifact:
        state.count("script")
        return ScriptArtifact(
            title=brief.title,
            hook="Look closer at the rocks.",
            scenes=[
                {
                    "index": i,
                    "narration": f"Scene {i + 1} narration about tide pools.",
                    "on_screen_text": f"Fact {i + 1}",
                    "visual_description": "A rocky tide pool at low tide",
                    "image_query": f"tide pool {i}",
                }
                for i in range(SCENES)
            ],
        )

    def run_visuals(
        script: ScriptArtifact,
        brief: ProductionBrief,
        store: DjangoProjectStore,
        *,
        user_urls: list[str],
        previous: VisualResult | None,
    ) -> VisualResult:
        state.count("visuals")
        if state.visuals_error is not None:
            raise state.visuals_error
        assets = []
        for scene in script.scenes:
            candidate = ImageCandidate(
                candidate_id=f"openverse:{scene.index}",
                provider="openverse",
                title=f"Pool {scene.index}",
                download_url=f"https://upload.example/{scene.index}.jpg",
                license="CC0" if state.rights == "documented" else "unknown",
                rights_status=state.rights,  # type: ignore[arg-type]
            )
            image = validate_image(_jpeg(["teal", "navy", "olive"][scene.index % 3]))
            saved = store.save_image(image, candidate, scene_index=scene.index)
            assets.append(SceneAsset(scene_index=scene.index, asset_id=saved["id"]))
        return VisualResult(scene_assets=assets)

    def synthesize(
        text: str, path: Path, config: narration.NarrationConfig | None = None
    ) -> narration.NarrationResult:
        state.count("narration")
        if state.narration_error is not None:
            raise state.narration_error
        path.write_bytes(b"ID3fake-mp3")
        return narration.NarrationResult(
            path=path, provider="edge", voice="en-US-AvaNeural", duration_seconds=12.0
        )

    def render_timeline(scenes: list[Any], output: Path, **kwargs: Any) -> RenderOutcome:
        state.count("render")
        output.write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
        missing = [i for i, scene in enumerate(scenes) if scene.image_path is None]
        return RenderOutcome(
            path=output,
            duration_seconds=sum(s.duration for s in scenes),
            has_audio=kwargs.get("narration_path") is not None,
            placeholder_scenes=missing,
        )

    def check_video(path: Path, **kwargs: Any) -> dict[str, Any]:
        state.count("qc")
        if not state.qc_passes:
            return {"passed": False, "problems": ["No audio stream"], "checks": []}
        return {"passed": True, "problems": [], "checks": [{"name": "opens", "ok": True}]}

    monkeypatch.setattr(specialists, "run_brief", run_brief)
    monkeypatch.setattr(specialists, "run_script", run_script)
    monkeypatch.setattr(specialists, "check_script", lambda script, brief: [])
    monkeypatch.setattr(specialists, "run_visuals", run_visuals)
    monkeypatch.setattr(narration, "synthesize", synthesize)
    monkeypatch.setattr(
        narration, "current_config", lambda: narration.NarrationConfig(provider="edge")
    )
    monkeypatch.setattr(production, "render_timeline", render_timeline)
    monkeypatch.setattr(production, "check_video", check_video)
    return state


def _run(
    studio: Studio, project: Project, personality: str = "director", **request: Any
) -> dict[str, Any]:
    store = DjangoProjectStore(project)
    with run_context(lambda event, data: studio.events.append((event, data))):
        return run_production(
            store, ProductionRequest(task="A short about tide pools", **request), personality
        )


def _statuses(project: Project) -> dict[str, str]:
    latest: dict[str, str] = {}
    for task in ProductionTask.objects.filter(project=project).order_by("created_at"):
        latest[task.stage] = task.status
    return latest


# --- production tasks ------------------------------------------------------------------


def test_full_run_verifies_every_stage_then_reuses_them(studio: Studio) -> None:
    project = Project.objects.create()
    result = _run(studio, project)

    assert result["qc"]["passed"] is True
    assert result["video"]["kind"] == "video"
    assert _statuses(project) == {
        "brief": "verified",
        "research": "skipped",
        "script": "verified",
        "visuals": "verified",
        "narration": "verified",
        "music": "skipped",
        "render": "verified",
        "qc": "verified",
    }
    assert MediaAsset.objects.filter(project=project, kind="image").count() == SCENES
    steps = [data for event, data in studio.events if event == "step"]
    assert {step["status"] for step in steps} == {"running", "done"}
    assert all(step["task_id"] for step in steps)
    assert "The cut is ready." in result["summary"]

    before = dict(studio.calls)
    again = _run(studio, project, personality="creative_partner")
    assert studio.calls == before
    assert again["reused_stages"] == [
        "brief",
        "script",
        "narration",
        "visuals",
        "render",
        "qc",
    ]
    assert "Here's what we made together." in again["summary"]


def test_from_stage_reruns_that_stage_and_downstream(studio: Studio) -> None:
    project = Project.objects.create()
    _run(studio, project)
    before = dict(studio.calls)
    _run(studio, project, from_stage="render")
    changed = {k for k, v in studio.calls.items() if v != before.get(k)}
    assert changed == {"render", "qc"}
    assert set(downstream_of("render")) == {"qc"}


def test_replacing_a_scene_image_invalidates_render_only(studio: Studio) -> None:
    project = Project.objects.create()
    _run(studio, project)
    replace_scene_asset(project, 1, None)
    statuses = _statuses(project)
    assert statuses["render"] == "invalidated"
    assert statuses["qc"] == "invalidated"
    assert statuses["visuals"] == "verified"

    before = dict(studio.calls)
    result = _run(studio, project)
    changed = {k for k, v in studio.calls.items() if v != before.get(k)}
    assert changed == {"render", "qc"}
    assert result["render"]["placeholder_scenes"] == [1]
    assert any("Title cards" in item for item in result["limitations"])


def test_unknown_rights_images_wait_for_approval_before_rendering(studio: Studio) -> None:
    project = Project.objects.create()
    studio.rights = "unknown"
    result = _run(studio, project)
    assert result["render"]["placeholder_scenes"] == [0, 1, 2]
    assert any("unknown reuse rights" in item for item in result["limitations"])

    approved = VisualResult.model_validate(
        ProductionTask.objects.filter(project=project, stage="visuals").latest("created_at").output
    ).asset_for(1)
    assert approved is not None
    replace_scene_asset(project, 1, MediaAsset.objects.get(pk=approved.asset_id))
    again = _run(studio, project)
    assert again["render"]["placeholder_scenes"] == [0, 2]


def test_cancel_marks_the_active_task_cancelled(studio: Studio) -> None:
    project = Project.objects.create()
    studio.visuals_error = RunCancelled()
    with pytest.raises(RunCancelled):
        _run(studio, project)
    statuses = _statuses(project)
    assert statuses["visuals"] == "cancelled"
    assert statuses["render"] == "proposed"
    assert statuses["script"] == "verified"


def test_narration_failure_resumes_without_redoing_images(studio: Studio) -> None:
    project = Project.objects.create()
    studio.narration_error = narration.NarrationError(
        "Edge TTS could not be reached.", provider="edge", retryable=True
    )
    with pytest.raises(narration.NarrationStageError) as raised:
        _run(studio, project)
    assert raised.value.render_spec == {"resume_production": True, "from_stage": "narration"}
    assert _statuses(project)["narration"] == "failed"
    assert _statuses(project)["visuals"] == "verified"

    studio.narration_error = None
    before = dict(studio.calls)
    result = _run(studio, project, from_stage="narration")
    changed = {k for k, v in studio.calls.items() if v != before.get(k)}
    assert changed == {"narration", "render", "qc"}
    assert result["qc"]["passed"] is True


def test_quality_check_failure_is_actionable(studio: Studio) -> None:
    project = Project.objects.create()
    studio.qc_passes = False
    with pytest.raises(ProductionStageError) as raised:
        _run(studio, project)
    assert raised.value.stage == "qc"
    assert raised.value.kind == "qc_failed"
    task = ProductionTask.objects.filter(project=project, stage="qc").latest("created_at")
    assert task.status == "failed"
    assert task.error["kind"] == "qc_failed"


def test_plan_only_stops_before_spending(studio: Studio) -> None:
    project = Project.objects.create()
    result = _run(studio, project, stop_after="script")
    assert result["script"] and result["video"] is None
    assert "visuals" not in studio.calls and "narration" not in studio.calls
    assert set(_statuses(project)) == {"brief", "research", "script"}


def test_silent_format_skips_narration(studio: Studio) -> None:
    project = Project.objects.create()
    result = _run(studio, project, short_format="text_short")
    assert result["narration"] is None
    assert _statuses(project)["narration"] == "skipped"
    assert "narration" not in studio.calls


# --- personalities and hierarchy -------------------------------------------------------


@dataclass
class FakeChatClient:
    reply: str = "Here's the plan."
    configs: list[Any] = field(default_factory=list)

    @property
    def models(self) -> FakeChatClient:
        return self

    def generate_content(self, *, contents: list[Any], config: Any) -> Any:
        self.configs.append(config)
        return type("Response", (), {"text": self.reply})()


def test_personalities_share_instructions_and_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeChatClient()
    monkeypatch.setattr(chat, "get_llm_client", lambda agent: fake)
    store = DjangoProjectStore(Project.objects.create())
    history = [chat.ChatTurn(role="user", content="Hi")]

    replies = [chat.run_orchestrator_chat(history, store, p) for p in PERSONALITIES]
    assert [reply.personality for reply in replies] == list(PERSONALITIES)
    prompts = [config.system_instruction for config in fake.configs]
    for personality, prompt in zip(PERSONALITIES, prompts, strict=True):
        assert prompt == chat.OPERATIONAL_PROMPT + personality_block(personality)
    tool_names = [[tool.__name__ for tool in config.tools] for config in fake.configs]
    assert tool_names[0] == tool_names[1]
    assert {config.temperature for config in fake.configs} == {0.6}
    assert chat.run_orchestrator_chat(history, store, "nonsense").personality == "director"


def test_specialists_cannot_delegate() -> None:
    with specialists.delegated("visual"):
        with pytest.raises(specialists.DelegationDepthExceeded):
            with specialists.delegated("research"):
                pass
    with specialists.delegated("research"):
        pass


def test_orchestrator_tools_limit_productions_and_reuse_the_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Project.objects.create()
    store = DjangoProjectStore(project)
    ProductionTask.objects.create(
        project=project,
        stage="brief",
        specialist="orchestrator",
        inputs={"task": "Tide pools", "context": "for kids"},
        status="verified",
    )
    seen: list[ProductionRequest] = []

    def fake_run(store: Any, request: ProductionRequest, personality: str) -> dict[str, Any]:
        seen.append(request)
        return {
            "summary": "done",
            "brief": {},
            "script": None,
            "video": {"id": "v"},
            "limitations": [],
        }

    monkeypatch.setattr(chat, "run_production", fake_run)
    tools = {tool.__name__: tool for tool in chat.OrchestratorTools(store, "director").tools()}
    first = json.loads(tools["produce_video"]())
    assert first["video_ready"] is True
    assert seen[0].task == "Tide pools" and seen[0].context == "for kids"
    second = json.loads(tools["produce_video"]("another one"))
    assert "Only one production" in second["error"]
    assert len(seen) == 1


def test_a_failed_plan_can_be_retried_in_the_same_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    store = DjangoProjectStore(Project.objects.create())
    attempts: list[str | None] = []

    def fake_run(store: Any, request: ProductionRequest, personality: str) -> dict[str, Any]:
        attempts.append(request.stop_after)
        if len(attempts) == 1:
            raise RuntimeError("Research failed")
        return {"summary": "planned", "brief": {}, "script": None, "limitations": []}

    monkeypatch.setattr(chat, "run_production", fake_run)
    tools = {tool.__name__: tool for tool in chat.OrchestratorTools(store, "director").tools()}

    assert "Research failed" in json.loads(tools["plan_video"]("Nami"))["error"]
    assert json.loads(tools["plan_video"]("Nami"))["summary"] == "planned"
    assert "planning attempts" in json.loads(tools["plan_video"]("Nami"))["error"]
    assert json.loads(tools["produce_video"]("Nami"))["video_ready"] is False
    assert attempts == ["script", "script", None]


# --- API -------------------------------------------------------------------------------


def test_personality_settings_and_project_override(client: APIClient) -> None:
    project = Project.objects.create()
    assert client.put(
        "/api/settings/personality", {"personality": "creative_partner"}, format="json"
    ).json() == {"personality": "creative_partner"}
    detail = client.get(f"/api/projects/{project.pk}").json()
    assert detail["personality"] in ("", None)
    assert detail["effective_personality"] == "creative_partner"

    GenerationJob.objects.create(project=project, kind="chat", status="running")
    patched = client.patch(
        f"/api/projects/{project.pk}", {"personality": "director"}, format="json"
    ).json()
    assert patched["effective_personality"] == "director"
    assert patched["personality_applies"] == "next_turn"
    assert (
        client.patch(f"/api/projects/{project.pk}", {"personality": "boss"}, format="json")
    ).status_code == 400


def test_rerun_and_scene_image_api(
    client: APIClient, studio: Studio, fake_providers: FakeRegistry
) -> None:
    configure_ai(key=KEY)
    project = Project.objects.create()
    _run(studio, project)

    state = client.get(f"/api/projects/{project.pk}").json()["production"]
    assert [task["stage"] for task in state["tasks"]][:3] == ["brief", "research", "script"]
    assert len(state["scenes"]) == SCENES
    assert all(scene["asset_id"] for scene in state["scenes"])

    cleared = client.put(
        f"/api/projects/{project.pk}/scenes/0/image", {"asset_id": None}, format="json"
    )
    assert cleared.status_code == 200
    scene = cleared.json()["scenes"][0]
    assert scene["asset_id"] is None and scene["gap"]

    other = MediaAsset.objects.filter(project=project, kind="image").first()
    assert other is not None
    restored = client.put(
        f"/api/projects/{project.pk}/scenes/0/image", {"asset_id": str(other.pk)}, format="json"
    ).json()
    assert restored["scenes"][0]["asset_id"] == str(other.pk)
    assert restored["scenes"][0]["selected_by"] == "user"
    assert (
        client.put(f"/api/projects/{project.pk}/scenes/9/image", {"asset_id": None}, format="json")
    ).status_code == 409

    before = dict(studio.calls)
    rerun = client.post(f"/api/projects/{project.pk}/production/rerun", {}, format="json")
    assert rerun.status_code == 202, rerun.json()
    job = GenerationJob.objects.get(pk=rerun.json()["job"]["id"])
    assert job.status == "succeeded", job.error
    changed = {k for k, v in studio.calls.items() if v != before.get(k)}
    assert changed == {"render", "qc"}

    deleted = client.delete(f"/api/media/{other.pk}")
    assert deleted.status_code == 204
    after = client.get(f"/api/projects/{project.pk}").json()["production"]
    assert after["scenes"][0]["asset_id"] is None
    assert {t["stage"]: t["status"] for t in after["tasks"]}["render"] == "invalidated"
