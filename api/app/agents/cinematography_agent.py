from typing import Any, Dict

from google.genai import types

from app.agents._planning import format_context, format_research_block, format_script_block
from app.agents.base import (
    AgentConfigurationError,
    get_gemini_client,
    get_gemini_model_name,
)
from app.models.production import CinematographyReport


class CinematographyAgentError(Exception):
    pass


def run_cinematography_agent(
    task: str,
    context: str | None = None,
    research: Dict[str, Any] | None = None,
    script: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Plan shot lists, camera movement, and scene composition."""
    normalized_task = " ".join(task.strip().split())
    if len(normalized_task) < 5:
        raise ValueError("task must contain at least five characters")

    try:
        client = get_gemini_client()
    except AgentConfigurationError as exc:
        raise CinematographyAgentError(str(exc)) from exc

    prompt = f"""
You are FrameFusion's Cinematography Agent for vertical 9:16 short-form video.

Task: {normalized_task}
{format_context(context)}
{format_research_block(research)}
{format_script_block(script)}

Create a shot list that works with stock b-roll and simple text/narration shorts.
Each shot needs framing (wide, medium, close, POV), camera movement
(static, pan, push-in, handheld feel), and duration_seconds.
Keep total runtime appropriate for a social short (15–60 seconds).
"""

    try:
        response = client.models.generate_content(
            model=get_gemini_model_name(),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CinematographyReport,
                temperature=0.3,
            ),
        )
        return CinematographyReport.model_validate_json(response.text).model_dump()
    except CinematographyAgentError:
        raise
    except Exception as exc:
        raise CinematographyAgentError(
            f"Cinematography agent failed: {exc}"
        ) from exc
