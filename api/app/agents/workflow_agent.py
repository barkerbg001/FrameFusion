from typing import Any, Dict

from google.genai import types

from app.agents._planning import format_context
from app.agents.base import (
    AgentConfigurationError,
    get_gemini_client,
    get_gemini_model_name,
)
from app.models.production import WorkflowPlan


class WorkflowAgentError(Exception):
    pass


def run_workflow_agent(
    task: str,
    context: str | None = None,
    director_brief: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Plan production phases, deadlines, and asset tracking."""
    normalized_task = " ".join(task.strip().split())
    if len(normalized_task) < 5:
        raise ValueError("task must contain at least five characters")

    try:
        client = get_gemini_client()
    except AgentConfigurationError as exc:
        raise WorkflowAgentError(str(exc)) from exc

    brief_block = ""
    if director_brief:
        brief_block = f"""
Director creative vision: {director_brief.get("creative_vision", "")}
Tone: {director_brief.get("tone", "")}
Assigned agents: {", ".join(
    item.get("agent_id", "")
    for item in director_brief.get("assignments", [])
    if isinstance(item, dict)
)}
"""

    prompt = f"""
You are FrameFusion's Producer Agent — workflow manager for short-form video.

Task: {normalized_task}
{format_context(context)}
{brief_block}

Build a practical production workflow for a vertical 9:16 short.
Include phases that map to agent_id values: producer, research, script,
cinematography, visual, voice, music_director, sound_design, editor.

Each phase needs a realistic deadline_note (e.g. "Day 1 morning", "Before render").
Track assets such as script, b-roll, narration audio, music bed, and final MP4.
List risks that could delay delivery.
"""

    try:
        response = client.models.generate_content(
            model=get_gemini_model_name(),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=WorkflowPlan,
                temperature=0.2,
            ),
        )
        return WorkflowPlan.model_validate_json(response.text).model_dump()
    except WorkflowAgentError:
        raise
    except Exception as exc:
        raise WorkflowAgentError(f"Producer workflow agent failed: {exc}") from exc
