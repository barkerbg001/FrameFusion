import os
from datetime import datetime, timezone
from typing import Any, Dict

from dotenv import load_dotenv
from google.genai import types
from pydantic import BaseModel, Field

from app.agents.base import (
    AgentConfigurationError,
    get_gemini_client,
    get_gemini_model_name,
)
from app.models.music_composer import MusicComposerReport, MusicProductionResult
from app.services.music_composer import MusicComposerError, compose_music
from app.services.output_filename import resolve_music_output_name


class MusicComposerAgentError(Exception):
    pass


class MusicPlan(BaseModel):
    provider_prompt: str = Field(
        ...,
        description="Detailed prompt for the music generation provider",
    )
    genre: str
    mood: str
    rationale: str
    limitations: list[str] = Field(default_factory=list)


def run_music_composer_agent(
    brief: str,
    context: str | None = None,
    duration_seconds: int = 30,
    mood: str | None = None,
    genre: str | None = None,
    instrumental: bool = True,
) -> Dict[str, Any]:
    """Plan and render background music for a brief."""
    normalized_brief = " ".join(brief.strip().split())
    if len(normalized_brief) < 3:
        raise ValueError("brief must contain at least three characters")
    if duration_seconds < 3 or duration_seconds > 600:
        raise ValueError("duration_seconds must be between 3 and 600")

    try:
        client = get_gemini_client()
    except AgentConfigurationError as exc:
        raise MusicComposerAgentError(str(exc)) from exc

    model = get_gemini_model_name()
    composed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    context_block = (
        f"\nScene or video context:\n{context.strip()}\n"
        if context and context.strip()
        else ""
    )
    mood_block = (
        f"\nRequested mood: {mood.strip()}\n"
        if mood and mood.strip()
        else ""
    )
    genre_block = (
        f"\nRequested genre: {genre.strip()}\n"
        if genre and genre.strip()
        else ""
    )
    provider_hint = "ElevenLabs Music"
    load_dotenv()
    if not os.getenv("ELEVENLABS_API_KEY"):
        provider_hint = "FrameFusion's free procedural composer"

    prompt = f"""
You are FrameFusion's music composer agent.

Brief: {normalized_brief}
Target duration: {duration_seconds} seconds
Instrumental only: {"yes" if instrumental else "no"}
Likely provider: {provider_hint}
{context_block}{mood_block}{genre_block}

Create a provider_prompt that describes the track clearly for AI music generation.
Include genre, mood, tempo feel, instrumentation, and how it should support the brief.
Keep provider_prompt under 500 characters. Avoid lyrics unless instrumental is false.
Return concise genre and mood labels, plus any production limitations.
"""

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=MusicPlan,
                temperature=0.2,
            ),
        )
        plan = MusicPlan.model_validate_json(response.text)
        output_name = resolve_music_output_name(normalized_brief, default_stem="track")
        music_result = compose_music(
            prompt=plan.provider_prompt,
            duration_seconds=duration_seconds,
            output_name=output_name,
            force_instrumental=instrumental,
        )

        limitations = list(plan.limitations)
        limitations.extend(music_result.get("limitations", []))
        if instrumental:
            limitations.append("Track requested as instrumental background music.")
        if not os.getenv("ELEVENLABS_API_KEY"):
            limitations.append(
                "ElevenLabs Music requires ELEVENLABS_API_KEY for higher-quality tracks."
            )
        if not limitations:
            limitations = ["Review the track before publishing commercially."]

        report = MusicComposerReport(
            brief=normalized_brief,
            composed_at=composed_at,
            genre=plan.genre,
            mood=plan.mood,
            rationale=plan.rationale,
            limitations=limitations,
            music=MusicProductionResult(
                audio_type="music",
                provider=music_result["provider"],
                output_path=music_result["output_path"],
                output_name=music_result["output_name"],
                prompt=music_result["prompt"],
                duration_seconds=music_result["duration_seconds"],
                force_instrumental=instrumental,
            ),
            composition_data={
                "provider_prompt": plan.provider_prompt,
                "requested_duration_seconds": duration_seconds,
                "music_result": music_result,
            },
        )
        return report.model_dump()
    except MusicComposerError as exc:
        raise MusicComposerAgentError(str(exc)) from exc
    except Exception as exc:
        raise MusicComposerAgentError(
            f"Music composer agent failed: {exc}"
        ) from exc
