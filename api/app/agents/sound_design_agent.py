from typing import Any, Dict

from google.genai import types

from app.agents._planning import format_context
from app.agents.base import (
    AgentConfigurationError,
    get_gemini_client,
    get_gemini_model_name,
)
from app.models.production import SoundDesignReport


class SoundDesignAgentError(Exception):
    pass


def run_sound_design_agent(
    task: str,
    context: str | None = None,
    cinematography: Dict[str, Any] | None = None,
    music_director: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Plan sound effects, ambient layers, and mix suggestions."""
    normalized_task = " ".join(task.strip().split())
    if len(normalized_task) < 5:
        raise ValueError("task must contain at least five characters")

    try:
        client = get_gemini_client()
    except AgentConfigurationError as exc:
        raise SoundDesignAgentError(str(exc)) from exc

    music_block = ""
    if music_director:
        music_block = f"""
Music style: {music_director.get("overall_style", "")}
Scene cues: {len(music_director.get("scene_cues", []))}
"""

    cinematography_block = ""
    if cinematography:
        cinematography_block = f"Pacing: {cinematography.get('pacing_notes', '')}"

    prompt = f"""
You are FrameFusion's Sound Design Agent for vertical 9:16 short-form video.

Task: {normalized_task}
{format_context(context)}
{cinematography_block}
{music_block}

Plan ambient_bed, sfx/foley layers, and mix_suggestions that complement
the music director's score. Keep layers realistic for stock b-roll shorts.
Note where narration and music should duck or sit in the mix.
"""

    try:
        response = client.models.generate_content(
            model=get_gemini_model_name(),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SoundDesignReport,
                temperature=0.35,
            ),
        )
        return SoundDesignReport.model_validate_json(response.text).model_dump()
    except SoundDesignAgentError:
        raise
    except Exception as exc:
        raise SoundDesignAgentError(
            f"Sound design agent failed: {exc}"
        ) from exc
