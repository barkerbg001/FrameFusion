from typing import Any, Dict

from google.genai import types

from app.agents._planning import format_context, format_research_block
from app.agents.base import (
    AgentConfigurationError,
    get_gemini_client,
    get_gemini_model_name,
)
from app.models.production import VisualReport


class VisualAgentError(Exception):
    pass


def run_visual_agent(
    task: str,
    context: str | None = None,
    research: Dict[str, Any] | None = None,
    cinematography: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Plan visuals, backgrounds, and asset requirements."""
    normalized_task = " ".join(task.strip().split())
    if len(normalized_task) < 5:
        raise ValueError("task must contain at least five characters")

    try:
        client = get_gemini_client()
    except AgentConfigurationError as exc:
        raise VisualAgentError(str(exc)) from exc

    cinematography_block = ""
    if cinematography:
        cinematography_block = f"""
Shot list summary:
{len(cinematography.get("shot_list", []))} planned shots
Composition notes: {", ".join(cinematography.get("composition_notes", []))}
"""

    prompt = f"""
You are FrameFusion's Visual Agent for vertical 9:16 short-form video.

Task: {normalized_task}
{format_context(context)}
{format_research_block(research)}
{cinematography_block}

Define the visual style, color palette, and required assets.
Prefer Pexels b-roll (source: pexels) with concrete search_query values.
Use text_overlay for on-screen captions and generated only when necessary.
Do not promise assets FrameFusion cannot yet generate automatically.
"""

    try:
        response = client.models.generate_content(
            model=get_gemini_model_name(),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=VisualReport,
                temperature=0.3,
            ),
        )
        return VisualReport.model_validate_json(response.text).model_dump()
    except VisualAgentError:
        raise
    except Exception as exc:
        raise VisualAgentError(f"Visual agent failed: {exc}") from exc
