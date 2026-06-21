import os
from typing import Any, Dict

from google.genai import types

from app.agents._planning import format_context, format_script_block
from app.agents.base import (
    AgentConfigurationError,
    get_gemini_client,
    get_gemini_model_name,
)
from app.models.production import VoiceReport


class VoiceAgentError(Exception):
    pass


def run_voice_agent(
    task: str,
    context: str | None = None,
    script: Dict[str, Any] | None = None,
    short_format: str = "auto",
) -> Dict[str, Any]:
    """Plan narration approach, voice selection, and delivery style."""
    normalized_task = " ".join(task.strip().split())
    if len(normalized_task) < 5:
        raise ValueError("task must contain at least five characters")

    try:
        client = get_gemini_client()
    except AgentConfigurationError as exc:
        raise VoiceAgentError(str(exc)) from exc

    elevenlabs_note = (
        "ElevenLabs is available for narration."
        if os.getenv("ELEVENLABS_API_KEY")
        else "ElevenLabs is not configured — note text-only fallback in limitations."
    )

    prompt = f"""
You are FrameFusion's Voice Agent for vertical 9:16 short-form video.

Task: {normalized_task}
Requested format: {short_format}
{format_context(context)}
{format_script_block(script)}

Plan narration and delivery. {elevenlabs_note}
Recommend voice_style (warm, authoritative, energetic, calm, etc.),
pacing, and delivery_notes for ElevenLabs TTS when narration is used.
If the short should be silent/text-only, say so in limitations.
"""

    try:
        response = client.models.generate_content(
            model=get_gemini_model_name(),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=VoiceReport,
                temperature=0.3,
            ),
        )
        report = VoiceReport.model_validate_json(response.text)
        if not os.getenv("ELEVENLABS_API_KEY"):
            limitations = list(report.limitations)
            limitations.append(
                "Narration requires ELEVENLABS_API_KEY; use text-only short otherwise."
            )
            report.limitations = limitations
        return report.model_dump()
    except VoiceAgentError:
        raise
    except Exception as exc:
        raise VoiceAgentError(f"Voice agent failed: {exc}") from exc
