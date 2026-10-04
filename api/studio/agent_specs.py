"""Specialists the user can run directly from the Agents page.

These run the same specialist code the orchestrator delegates to. Productions
(images, narration, render, QC) only run through the orchestrator so every
stage is a tracked task.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from engine.llm import Route, route_for
from engine.orchestrator.schemas import ProductionBrief, ScriptArtifact
from engine.schemas.idea import IdeaReport, IdeaRequest
from engine.schemas.music_composer import MusicComposerReport, MusicComposerRequest
from engine.schemas.researcher import ResearcherReport, ResearcherRequest


class ScriptRequest(BaseModel):
    task: str = Field(min_length=5, max_length=3000)
    context: str | None = Field(default=None, max_length=4000)
    research: str | None = Field(default=None, max_length=8000)
    format: Literal["narrated", "silent"] = "narrated"
    target_seconds: int = Field(default=40, ge=15, le=90)
    scene_count: int = Field(default=5, ge=3, le=8)


class ScriptReport(ScriptArtifact):
    problems: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class AgentSpec:
    slug: str
    agent_id: str
    label: str
    request_model: type[BaseModel]
    response_model: type[BaseModel]
    run: Callable[[Any], dict[str, Any]]
    renders_media: bool = False

    @property
    def routes(self) -> tuple[Route, ...]:
        return (route_for(self.agent_id),)


def _ideas(r: IdeaRequest) -> dict[str, Any]:
    from engine.agents.idea_agent import run_idea_agent

    return run_idea_agent(
        topic=r.topic, context=r.context, audience=r.audience, idea_count=r.idea_count
    )


def _research(r: ResearcherRequest) -> dict[str, Any]:
    from engine.orchestrator.specialists import run_research

    return run_research(r.task, r.context or "")


def _script(r: ScriptRequest) -> dict[str, Any]:
    from engine.orchestrator.specialists import check_script, run_script

    brief = ProductionBrief(
        title=r.task[:90] if len(r.task) >= 2 else "Untitled",
        objective=(r.task + (f" ({r.context})" if r.context else ""))[:400],
        format=r.format,
        target_seconds=r.target_seconds,
        scene_count=r.scene_count,
    )
    research = {"summary": r.research} if r.research else None
    script = run_script(brief, research)
    return {**script.model_dump(), "problems": check_script(script, brief)}


def _compose_music(r: MusicComposerRequest) -> dict[str, Any]:
    from engine.agents.music_composer_agent import run_music_composer_agent

    return run_music_composer_agent(
        brief=r.brief,
        context=r.context,
        duration_seconds=r.duration_seconds,
        mood=r.mood,
        genre=r.genre,
        instrumental=r.instrumental,
    )


AGENT_SPECS: dict[str, AgentSpec] = {
    spec.slug: spec
    for spec in (
        AgentSpec("ideas", "ideas", "Idea generation", IdeaRequest, IdeaReport, _ideas),
        AgentSpec(
            "research", "research", "Research", ResearcherRequest, ResearcherReport, _research
        ),
        AgentSpec("script", "script", "Script and scenes", ScriptRequest, ScriptReport, _script),
        AgentSpec(
            "compose-music",
            "music_composer",
            "Music composition",
            MusicComposerRequest,
            MusicComposerReport,
            _compose_music,
            renders_media=True,
        ),
    )
}


def run_spec(spec: AgentSpec, payload: dict[str, Any]) -> dict[str, Any]:
    request = spec.request_model.model_validate(payload)
    result = spec.run(request)
    return spec.response_model(**result).model_dump(mode="json")
