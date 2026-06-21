import os
from typing import Any, Dict

from google.genai import types

from app.agents._planning import format_context, format_script_block
from app.agents.base import (
    AgentConfigurationError,
    get_gemini_client,
    get_gemini_model_name,
)
from app.models.production import MusicDirectorReport


class MusicDirectorAgentError(Exception):
    pass


def run_music_director_agent(
    task: str,
    context: str | None = None,
    script: Dict[str, Any] | None = None,
    cinematography: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Plan music style, scene moods, and generation prompts."""
    normalized_task = " ".join(task.strip().split())
    if len(normalized_task) < 5:
        raise ValueError("task must contain at least five characters")

    try:
        client = get_gemini_client()
    except AgentConfigurationError as exc:
        raise MusicDirectorAgentError(str(exc)) from exc

    cinematography_block = ""
    if cinematography:
        shots = cinematography.get("shot_list", [])
        cinematography_block = f"Planned shots: {len(shots)}. Pacing: {cinematography.get('pacing_notes', '')}"

    provider_note = (
        "Music will be generated via ElevenLabs Music when configured."
        if os.getenv("ELEVENLABS_API_KEY")
        else "Music will use FrameFusion's procedural fallback without ElevenLabs."
    )

    prompt = f"""
You are FrameFusion's Music Director Agent for vertical 9:16 short-form video.

Task: {normalized_task}
{format_context(context)}
{format_script_block(script)}
{cinematography_block}

{provider_note}

Define overall_style and scene_cues with ready-to-use music_prompt strings
for each scene or act. Include mood, genre, tempo, duration_seconds, and
transition_note between cues. Prompts must request instrumental, no vocals.
"""

    try:
        response = client.models.generate_content(
            model=get_gemini_model_name(),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=MusicDirectorReport,
                temperature=0.35,
            ),
        )
        report = MusicDirectorReport.model_validate_json(response.text)
        if not os.getenv("ELEVENLABS_API_KEY"):
            limitations = list(report.limitations)
            limitations.append(
                "Set ELEVENLABS_API_KEY for higher-quality AI music generation."
            )
            report.limitations = limitations
        return report.model_dump()
    except MusicDirectorAgentError:
        raise
    except Exception as exc:
        raise MusicDirectorAgentError(
            f"Music director agent failed: {exc}"
        ) from exc
