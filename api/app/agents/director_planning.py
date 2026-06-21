from datetime import datetime, timezone
from typing import Any, Dict

from google.genai import types

from app.agents._planning import format_context
from app.agents.base import (
    AgentConfigurationError,
    get_gemini_client,
    get_gemini_model_name,
)
from app.agents.registry import PRODUCTION_AGENTS
from app.models.production import AgentAssignment, DirectorBrief


class DirectorPlanningError(Exception):
    pass


def run_director_brief(
    task: str,
    context: str | None = None,
) -> Dict[str, Any]:
    """Set creative vision and assign specialist agents for a production."""
    normalized_task = " ".join(task.strip().split())
    if len(normalized_task) < 5:
        raise ValueError("task must contain at least five characters")

    try:
        client = get_gemini_client()
    except AgentConfigurationError as exc:
        raise DirectorPlanningError(str(exc)) from exc

    roster = "\n".join(
        f"- {agent.emoji} {agent.name}: {', '.join(agent.responsibilities)}"
        for agent in PRODUCTION_AGENTS
        if agent.id not in {"renderer"}
    )
    prompt = f"""
You are FrameFusion's Director Agent.

Task: {normalized_task}
{format_context(context)}

Available specialist agents:
{roster}

Define the creative vision for this short-form vertical video production.
Assign each relevant specialist with a clear objective. Use agent_id values exactly:
director, producer, research, script, cinematography, visual, voice,
music_director, sound_design, editor.

Mark research and script as required for factual or narrative shorts.
Include cinematography, visual, voice, music_director, and sound_design when
the production benefits from them. Always include producer for workflow planning
and editor when a rendered video is expected.

Keep approval_notes practical — what the Director must sign off on before publish.
"""

    try:
        response = client.models.generate_content(
            model=get_gemini_model_name(),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=DirectorBrief,
                temperature=0.3,
            ),
        )
        brief = DirectorBrief.model_validate_json(response.text)
        if not brief.assignments:
            brief.assignments = [
                AgentAssignment(
                    agent_id="research",
                    objective="Gather verified facts and references",
                    priority="required",
                ),
                AgentAssignment(
                    agent_id="script",
                    objective="Write the short-form script",
                    priority="required",
                ),
                AgentAssignment(
                    agent_id="editor",
                    objective="Assemble and render the final video",
                    priority="required",
                ),
            ]
        return brief.model_dump()
    except DirectorPlanningError:
        raise
    except Exception as exc:
        raise DirectorPlanningError(f"Director brief failed: {exc}") from exc
