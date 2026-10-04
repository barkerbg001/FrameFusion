"""The orchestrator's production run.

Stages run in dependency order and each one is a persisted task. A stage whose
inputs hash matches its last verified task is reused, so retrying a failed
production (or re-rendering after replacing an image) only redoes what changed.
Narration runs in parallel with the visual specialist because both depend only
on the script. Every artifact is verified before downstream work uses it, and
the final video is re-opened by QC before the run is reported as complete.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any

from engine.orchestrator import specialists
from engine.orchestrator.personalities import get_personality
from engine.orchestrator.schemas import (
    DEPENDS_ON,
    STAGE_LABELS,
    STAGE_SPECIALIST,
    STAGES,
    NarrationArtifact,
    ProductionBrief,
    ProductionRequest,
    QCReport,
    RenderArtifact,
    ScriptArtifact,
    TaskRecord,
    VisualResult,
    downstream_of,
)
from engine.orchestrator.store import ProjectStore
from engine.runtime import RunCancelled, check_cancelled, report
from engine.services import narration as narration_service
from engine.services.images.candidates import safe_slug
from engine.services.images.variants import render_variant
from engine.services.procedural_music import generate_procedural_music
from engine.services.text_video_creator import timed_screen_durations
from engine.services.timeline import TimelineScene, check_video, render_timeline

MAX_STAGE_ATTEMPTS = 2


class ProductionStageError(Exception):
    """A stage failed in a way the user can act on."""

    def __init__(
        self, message: str, *, stage: str, kind: str = "stage_failed", retryable: bool = True
    ) -> None:
        super().__init__(message)
        self.message = message
        self.stage = stage
        self.kind = kind
        self.retryable = retryable

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "stage": self.stage,
            "retryable": self.retryable,
        }


def input_hash(stage: str, inputs: Any) -> str:
    payload = json.dumps([stage, inputs], sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


@dataclass
class StageResult:
    output: dict[str, Any]
    artifact_ids: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


class Production:
    def __init__(
        self, store: ProjectStore, request: ProductionRequest, personality: str | None
    ) -> None:
        self.store = store
        self.request = request
        self.personality = get_personality(personality)
        self.forced: set[str] = set()
        if request.from_stage:
            self.forced = {request.from_stage, *downstream_of(request.from_stage)}
        self.limitations: list[str] = []
        self.outputs: dict[str, dict[str, Any]] = {}
        self.reused: list[str] = []

    # -- task bookkeeping -----------------------------------------------

    def _task_for(self, stage: str, digest: str, inputs: dict[str, Any]) -> tuple[TaskRecord, bool]:
        """Return (task, reusable). Reusable tasks are verified with identical inputs."""
        previous = self.store.latest_task(stage)
        if previous is not None and previous.input_hash == digest and stage not in self.forced:
            if previous.status in ("verified", "skipped"):
                return previous, True
            if previous.status == "invalidated" and previous.output is not None:
                # Identical inputs produce an identical artifact; upstream churn doesn't matter.
                return self.store.update_task(previous.id, status="verified"), True
        if (
            previous is not None
            and previous.status not in ("verified", "skipped", "active")
            and (previous.input_hash in ("", digest))
        ):
            return self.store.update_task(previous.id, input_hash=digest, inputs=inputs), False
        if previous is not None and previous.status == "verified":
            self.store.update_task(previous.id, status="invalidated")
        return (
            self.store.create_task(
                stage=stage,
                specialist=STAGE_SPECIALIST[stage],
                objective=STAGE_LABELS[stage],
                inputs=inputs,
                depends_on=list(DEPENDS_ON[stage]),
                input_hash=digest,
                max_attempts=MAX_STAGE_ATTEMPTS,
            ),
            False,
        )

    def _begin(
        self, stage: str, inputs: dict[str, Any]
    ) -> tuple[TaskRecord, dict[str, Any] | None]:
        check_cancelled()
        digest = input_hash(stage, inputs)
        task, reusable = self._task_for(stage, digest, inputs)
        agent = STAGE_SPECIALIST[stage]
        if reusable and task.output is not None:
            self.reused.append(stage)
            self.limitations.extend(
                item for item in task.limitations if item not in self.limitations
            )
            report("step", agent=agent, stage=stage, status="reused", task_id=task.id)
            return task, task.output
        task = self.store.update_task(
            task.id, status="active", attempt=task.attempt + 1, error=None
        )
        report("step", agent=agent, stage=stage, status="running", task_id=task.id)
        return task, None

    def _complete(self, stage: str, task: TaskRecord, result: StageResult) -> dict[str, Any]:
        previous_output = task.output
        self.store.update_task(
            task.id, status="completed", output=result.output, artifact_ids=result.artifact_ids
        )
        self.store.update_task(task.id, status="verified", limitations=result.limitations)
        self.limitations.extend(item for item in result.limitations if item not in self.limitations)
        if previous_output != result.output:
            self.store.invalidate(downstream_of(stage), reason=f"{STAGE_LABELS[stage]} changed")
        report("step", agent=STAGE_SPECIALIST[stage], stage=stage, status="done", task_id=task.id)
        return result.output

    def _fail(self, stage: str, task: TaskRecord, exc: BaseException) -> None:
        cancelled = isinstance(exc, RunCancelled)
        error = (
            exc.to_dict()
            if isinstance(exc, ProductionStageError)
            else {
                "kind": "cancelled" if cancelled else type(exc).__name__,
                "message": str(exc)[:500],
            }
        )
        self.store.update_task(task.id, status="cancelled" if cancelled else "failed", error=error)
        report(
            "step",
            agent=STAGE_SPECIALIST[stage],
            stage=stage,
            status="cancelled" if cancelled else "failed",
            task_id=task.id,
        )

    def _run(
        self, stage: str, inputs: dict[str, Any], work: Callable[[], StageResult]
    ) -> dict[str, Any]:
        task, reused = self._begin(stage, inputs)
        if reused is not None:
            return reused
        try:
            result = work()
        except BaseException as exc:
            self._fail(stage, task, exc)
            raise
        return self._complete(stage, task, result)

    def _skip(self, stage: str, reason: str) -> None:
        digest = input_hash(stage, {"skipped": reason})
        previous = self.store.latest_task(stage)
        if previous is not None and previous.status == "skipped" and previous.input_hash == digest:
            return
        if previous is not None and previous.status == "verified":
            self.store.update_task(previous.id, status="invalidated")
        task = self.store.create_task(
            stage=stage,
            specialist=STAGE_SPECIALIST[stage],
            objective=STAGE_LABELS[stage],
            inputs={"reason": reason},
            depends_on=list(DEPENDS_ON[stage]),
            input_hash=digest,
            max_attempts=1,
            status="skipped",
        )
        self.store.update_task(task.id, output={"skipped": reason})

    def _propose(self, stages: list[str]) -> None:
        """Record the plan: every stage this production needs that has no live task yet."""
        for stage in stages:
            previous = self.store.latest_task(stage)
            if previous is None or previous.status == "skipped":
                self.store.create_task(
                    stage=stage,
                    specialist=STAGE_SPECIALIST[stage],
                    objective=STAGE_LABELS[stage],
                    inputs={},
                    depends_on=list(DEPENDS_ON[stage]),
                    input_hash="",
                    max_attempts=MAX_STAGE_ATTEMPTS,
                )

    # -- stages ---------------------------------------------------------

    def _brief(self) -> ProductionBrief:
        inputs = {
            "task": self.request.task,
            "context": self.request.context,
            "format": self.request.short_format,
        }

        def work() -> StageResult:
            brief = specialists.run_brief(self.request)
            return StageResult(brief.model_dump(), limitations=[])

        return ProductionBrief.model_validate(self._run("brief", inputs, work))

    def _research(self, brief: ProductionBrief) -> dict[str, Any] | None:
        if not brief.needs_research:
            self._skip("research", "The brief doesn't depend on facts that need checking.")
            return None
        questions = "; ".join(brief.research_questions) or brief.objective
        inputs = {"objective": brief.objective, "questions": brief.research_questions}

        def work() -> StageResult:
            report_data = specialists.run_research(f"{brief.title}: {questions}", brief.objective)
            if not str(report_data.get("summary") or "").strip():
                raise ProductionStageError("Research returned no findings.", stage="research")
            return StageResult(
                report_data, limitations=list(report_data.get("limitations") or [])[:3]
            )

        return self._run("research", inputs, work)

    def _script(self, brief: ProductionBrief, research: dict[str, Any] | None) -> ScriptArtifact:
        facts = (
            {key: research.get(key) for key in ("summary", "verified_facts", "citations")}
            if research
            else None
        )
        inputs = {"brief": brief.model_dump(), "research": facts}

        def work() -> StageResult:
            feedback: list[str] = []
            script: ScriptArtifact | None = None
            for attempt in range(MAX_STAGE_ATTEMPTS):
                try:
                    script = specialists.run_script(brief, research, feedback or None)
                except specialists.SpecialistError as exc:
                    feedback = exc.problems or [str(exc)]
                    if attempt + 1 == MAX_STAGE_ATTEMPTS:
                        raise ProductionStageError(
                            "The script specialist didn't return a usable script: "
                            + "; ".join(feedback[:3]),
                            stage="script",
                            kind="invalid_artifact",
                        ) from exc
                    report(
                        "message", agent="orchestrator", message="Sent the script back with fixes"
                    )
                    continue
                feedback = specialists.check_script(script, brief)
                if not feedback:
                    break
                if attempt + 1 < MAX_STAGE_ATTEMPTS:
                    report(
                        "message", agent="orchestrator", message="Sent the script back with fixes"
                    )
            assert script is not None
            return StageResult(
                script.model_dump(), limitations=[f"Script: {item}" for item in feedback]
            )

        return ScriptArtifact.model_validate(self._run("script", inputs, work))

    def _visuals(self, brief: ProductionBrief, script: ScriptArtifact) -> VisualResult:
        inputs = {
            "scenes": [
                {"q": scene.image_query, "v": scene.visual_description} for scene in script.scenes
            ],
            "urls": self.request.user_urls,
        }
        previous_task = self.store.latest_task("visuals")
        previous = (
            VisualResult.model_validate(previous_task.output)
            if previous_task
            and previous_task.output
            and previous_task.status != "skipped"
            and "scene_assets" in previous_task.output
            and len(previous_task.output.get("scene_assets") or []) <= len(script.scenes)
            and previous_task.inputs.get("scenes") == inputs["scenes"]
            else None
        )

        def work() -> StageResult:
            result = specialists.run_visuals(
                script, brief, self.store, user_urls=self.request.user_urls, previous=previous
            )
            searches = [search for state in result.scenes for search in state.searches]
            if not result.scene_assets and searches and all(s.get("error") for s in searches):
                raise ProductionStageError(
                    "No image source could be reached. "
                    + (" ".join(result.limitations[:2]) or "Check your connection and try again."),
                    stage="visuals",
                    kind="no_images",
                )
            limitations = list(result.limitations)
            limitations += [
                f"Scene {gap.scene_index + 1} has no suitable image: {gap.reason}"
                for gap in result.gaps
                if (state := result.scene_state(gap.scene_index)) is None
                or state.status != "title_card"
            ]
            return StageResult(
                result.model_dump(),
                artifact_ids=[item.asset_id for item in result.scene_assets],
                limitations=limitations,
            )

        return VisualResult.model_validate(self._run("visuals", inputs, work))

    def _narration_inputs(
        self, script: ScriptArtifact, config: narration_service.NarrationConfig
    ) -> dict[str, Any]:
        return {
            "text": script.narration_text,
            "provider": config.provider,
            "voice": config.voice,
            "rate": config.rate,
            "pitch": config.pitch,
            "volume": config.volume,
        }

    def _narration_result(
        self, script: ScriptArtifact, result: narration_service.NarrationResult
    ) -> StageResult:
        durations = timed_screen_durations(
            [scene.narration for scene in script.scenes],
            result.words or None,
            result.duration_seconds,
        )
        asset = self.store.register_output(
            result.path,
            role="narration",
            duration_seconds=result.duration_seconds,
            metadata=result.metadata(),
        )
        artifact = NarrationArtifact(
            asset_id=asset["id"],
            provider=result.provider,
            voice=result.voice,
            duration_seconds=result.duration_seconds,
            words=result.words,
            scene_durations=durations,
        )
        limitations = (
            []
            if result.words
            else ["Scene cuts follow word counts (the voice gave no word timings)."]
        )
        return StageResult(
            artifact.model_dump(), artifact_ids=[asset["id"]], limitations=limitations
        )

    def _music(self, brief: ProductionBrief, total_seconds: float) -> dict[str, Any] | None:
        if not brief.background_music:
            self._skip("music", "No music was requested.")
            return None
        inputs = {
            "tone": brief.tone,
            "style": brief.visual_style,
            "seconds": math.ceil(total_seconds),
        }

        def work() -> StageResult:
            path = self.store.new_output_path(f"{safe_slug(brief.title)}-music", ".wav")
            generate_procedural_music(
                f"{brief.tone} {brief.visual_style}", str(path), math.ceil(total_seconds) + 1
            )
            asset = self.store.register_output(path, role="music", duration_seconds=total_seconds)
            return StageResult(
                {"asset_id": asset["id"], "source": "procedural"},
                artifact_ids=[asset["id"]],
                limitations=["Music is a simple procedurally generated bed."],
            )

        return self._run("music", inputs, work)

    def _scene_durations(
        self, brief: ProductionBrief, script: ScriptArtifact, narration: NarrationArtifact | None
    ) -> list[float]:
        if narration and len(narration.scene_durations) == len(script.scenes):
            return narration.scene_durations
        raw = [scene.duration_seconds for scene in script.scenes]
        scale = brief.target_seconds / sum(raw) if sum(raw) else 1.0
        return [max(2.0, value * scale) for value in raw]

    @staticmethod
    def _caption(scene_text: str, narration: str) -> str:
        if scene_text.strip():
            return scene_text.strip()
        first = narration.split(". ")[0].strip()
        return first if len(first) <= 90 else first[:87].rsplit(" ", 1)[0] + "…"

    def _render(
        self,
        brief: ProductionBrief,
        script: ScriptArtifact,
        visuals: VisualResult,
        narration: NarrationArtifact | None,
        music: dict[str, Any] | None,
    ) -> RenderArtifact:
        durations = self._scene_durations(brief, script, narration)
        inputs = {
            "scenes": [(s.on_screen_text, s.narration) for s in script.scenes],
            "assets": [item.model_dump() for item in visuals.scene_assets],
            "durations": [round(d, 2) for d in durations],
            "narration": narration.asset_id if narration else None,
            "music": music.get("asset_id") if music else None,
        }

        def work() -> StageResult:
            timeline = []
            needs_rights_review: list[int] = []
            for scene, duration in zip(script.scenes, durations, strict=True):
                chosen = visuals.asset_for(scene.index)
                path = None
                if chosen is not None:
                    record = self.store.asset(chosen.asset_id) or {}
                    approved = (
                        record.get("rights_status") == "documented"
                        or record.get("user_supplied")
                        or chosen.selected_by == "user"
                    )
                    if approved:
                        original = self.store.asset_path(chosen.asset_id)
                        path = render_variant(original) if original else None
                    else:
                        needs_rights_review.append(scene.index)
                timeline.append(
                    TimelineScene(
                        duration=duration,
                        caption=self._caption(scene.on_screen_text, scene.narration),
                        image_path=path,
                        placeholder_text=scene.on_screen_text or scene.visual_description,
                    )
                )
            output = self.store.new_output_path(safe_slug(brief.title, "framefusion-short"), ".mp4")
            outcome = render_timeline(
                timeline,
                output,
                narration_path=self.store.asset_path(narration.asset_id) if narration else None,
                music_path=self.store.asset_path(music["asset_id"]) if music else None,
            )
            asset = self.store.register_output(
                outcome.path,
                role="video",
                duration_seconds=outcome.duration_seconds,
                metadata={"title": brief.title, "scenes": len(timeline)},
            )
            artifact = RenderArtifact(
                asset_id=asset["id"],
                file_name=outcome.path.name,
                duration_seconds=outcome.duration_seconds,
                scene_count=len(timeline),
                placeholder_scenes=outcome.placeholder_scenes,
            )
            limitations = (
                [
                    "Title cards were used for scenes without a suitable image: "
                    + ", ".join(str(i + 1) for i in outcome.placeholder_scenes)
                ]
                if outcome.placeholder_scenes
                else []
            )
            if needs_rights_review:
                limitations.append(
                    "Images with unknown reuse rights were left out until you approve them "
                    "(scenes " + ", ".join(str(i + 1) for i in needs_rights_review) + ")."
                )
            return StageResult(
                artifact.model_dump(), artifact_ids=[asset["id"]], limitations=limitations
            )

        return RenderArtifact.model_validate(self._run("render", inputs, work))

    def _qc(self, brief: ProductionBrief, render: RenderArtifact, expect_audio: bool) -> QCReport:
        inputs = {"render": render.asset_id, "audio": expect_audio}

        def work() -> StageResult:
            path = self.store.asset_path(render.asset_id)
            if path is None:
                raise ProductionStageError(
                    "The rendered video is missing.", stage="qc", kind="qc_failed"
                )
            result = QCReport.model_validate(
                check_video(
                    path,
                    expected_seconds=render.duration_seconds,
                    expect_audio=expect_audio,
                    unresolved_scenes=render.placeholder_scenes,
                )
            )
            if not result.passed:
                raise ProductionStageError(
                    "The video failed its quality check: " + "; ".join(result.problems),
                    stage="qc",
                    kind="qc_failed",
                )
            return StageResult(result.model_dump())

        return QCReport.model_validate(self._run("qc", inputs, work))

    # -- orchestration --------------------------------------------------

    def _stop(self, stage: str) -> bool:
        return self.request.stop_after == stage

    def run(self) -> dict[str, Any]:
        report(
            "message",
            agent="orchestrator",
            message=f"{self.personality.name} is planning the production",
        )
        brief = self._brief()
        self.outputs["brief"] = brief.model_dump()
        needed = ["script", "visuals"]
        if brief.needs_research:
            needed.insert(0, "research")
        if brief.format == "narrated":
            needed.append("narration")
        if brief.background_music:
            needed.append("music")
        if self.request.render_video:
            needed += ["render", "qc"]
        if self.request.stop_after:
            cutoff = STAGES.index(self.request.stop_after)
            needed = [stage for stage in needed if STAGES.index(stage) <= cutoff]
        self._propose(needed)
        if self._stop("brief"):
            return self._result(brief)

        research = self._research(brief)
        if self._stop("research"):
            return self._result(brief)
        script = self._script(brief, research)
        self.outputs["script"] = script.model_dump()
        if self._stop("script"):
            return self._result(brief, script=script)

        narration: NarrationArtifact | None = None
        pending: tuple[TaskRecord, Future[Any]] | None = None
        if brief.format == "narrated" and "narration" in needed:
            config = narration_service.current_config()
            task, reused = self._begin("narration", self._narration_inputs(script, config))
            if reused is not None:
                narration = NarrationArtifact.model_validate(reused)
            else:
                path = self.store.new_output_path(f"{safe_slug(brief.title)}-narration", ".mp3")
                text = script.narration_text
                pending = (
                    task,
                    self.store.run_in_thread(
                        lambda: narration_service.synthesize(text, path, config)
                    ),
                )
        elif brief.format == "silent":
            self._skip("narration", "Silent format: captions only.")

        try:
            visuals = self._visuals(brief, script)
        except BaseException:
            if pending is not None:
                self._settle_narration(script, brief, *pending, raise_errors=False)
            raise
        self.outputs["visuals"] = visuals.model_dump()
        if pending is not None:
            narration = self._settle_narration(script, brief, *pending, raise_errors=True)
        if self._stop("visuals") or self._stop("narration"):
            return self._result(brief, script=script, visuals=visuals, narration=narration)

        total = sum(self._scene_durations(brief, script, narration))
        music = self._music(brief, total)
        if not self.request.render_video or self._stop("music"):
            return self._result(brief, script=script, visuals=visuals, narration=narration)

        render = self._render(brief, script, visuals, narration, music)
        qc = self._qc(brief, render, expect_audio=narration is not None or music is not None)
        return self._result(
            brief, script=script, visuals=visuals, narration=narration, render=render, qc=qc
        )

    def _settle_narration(
        self,
        script: ScriptArtifact,
        brief: ProductionBrief,
        task: TaskRecord,
        future: Future[Any],
        *,
        raise_errors: bool,
    ) -> NarrationArtifact | None:
        try:
            result = future.result(timeout=600)
        except BaseException as exc:
            self._fail("narration", task, exc)
            if not raise_errors:
                return None
            if narration_service.find_narration_error(exc) is not None:
                raise narration_service.NarrationStageError(
                    f"{exc} {narration_service.SETTINGS_HINT}",
                    {"resume_production": True, "from_stage": "narration"},
                ) from exc
            raise
        return NarrationArtifact.model_validate(
            self._complete("narration", task, self._narration_result(script, result))
        )

    def _result(
        self,
        brief: ProductionBrief,
        *,
        script: ScriptArtifact | None = None,
        visuals: VisualResult | None = None,
        narration: NarrationArtifact | None = None,
        render: RenderArtifact | None = None,
        qc: QCReport | None = None,
    ) -> dict[str, Any]:
        video = self.store.asset(render.asset_id) if render else None
        return {
            "personality": self.personality.id,
            "brief": brief.model_dump(),
            "script": script.model_dump() if script else None,
            "visuals": visuals.model_dump() if visuals else None,
            "narration": narration.model_dump(exclude={"words"}) if narration else None,
            "render": render.model_dump() if render else None,
            "qc": qc.model_dump() if qc else None,
            "video": video,
            "reused_stages": self.reused,
            "limitations": self.limitations,
            "summary": self.summary(brief, script, visuals, narration, render, qc),
        }

    def summary(
        self,
        brief: ProductionBrief,
        script: ScriptArtifact | None,
        visuals: VisualResult | None,
        narration: NarrationArtifact | None,
        render: RenderArtifact | None,
        qc: QCReport | None,
    ) -> str:
        p = self.personality
        lines: list[str] = []
        if render and qc and qc.passed:
            lines.append(
                f"{p.finished} **{brief.title}** — {render.duration_seconds:.0f}s, "
                f"{render.scene_count} scenes, 1080×1920."
            )
        elif script:
            lines.append(f"**{brief.title}** is planned: {len(script.scenes)} scenes.")
        else:
            lines.append(f"Brief ready: **{brief.title}**.")
        if visuals:
            sources = sorted(
                {
                    str((self.store.asset(item.asset_id) or {}).get("provider") or "")
                    for item in visuals.scene_assets
                }
                - {""}
            )
            scene_total = len(script.scenes) if script else 0
            lines.append(
                f"Images: {len(visuals.scene_assets)} of {scene_total} scenes"
                + (f" ({', '.join(sources)})" if sources else "")
                + ". Credits and licences are in the Scenes tab."
            )
            unresolved = [
                state.scene_index + 1
                for state in visuals.scenes
                if state.status in ("awaiting_review", "no_suitable_result", "download_failed")
            ]
            if unresolved:
                lines.append(
                    "No suitable image yet for scene(s) "
                    + ", ".join(str(n) for n in unresolved)
                    + ": they use title cards until you choose, upload or paste one."
                )
        if narration:
            voice = narration_service.PROVIDER_LABELS.get(narration.provider, narration.provider)
            lines.append(f"Narration: {voice}, {narration.duration_seconds:.0f}s.")
        if self.reused:
            lines.append("Reused: " + ", ".join(STAGE_LABELS[s].lower() for s in self.reused) + ".")
        if self.limitations:
            lines.append(f"\n**{p.gaps}:**")
            lines.extend(f"- {item}" for item in self.limitations[:6])
        return "\n".join(lines)


def run_production(
    store: ProjectStore, request: ProductionRequest, personality: str | None
) -> dict[str, Any]:
    return Production(store, request, personality).run()
