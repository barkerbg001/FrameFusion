import os
from datetime import datetime, timezone
from typing import Any, Dict, Literal

from google.genai import types
from pydantic import BaseModel, Field

from app.agents.base import (
    AgentConfigurationError,
    get_gemini_client,
    get_gemini_model_name,
)
from app.models.producer import ProducerReport
from app.models.video_tools import VideoProductionResult
from app.services.output_filename import resolve_output_name
from app.services.video_producer import (
    VideoProducerError,
    produce_sound_short_simple,
    produce_text_short_simple,
)


ShortFormat = Literal["auto", "sound", "silent"]
InternalFormat = Literal["text_short", "sound_short"]


class ProducerAgentError(Exception):
    pass


class ProducerPlan(BaseModel):
    short_format: InternalFormat
    rationale: str
    limitations: list[str] = Field(default_factory=list)


def _map_short_format(short_format: str) -> str:
    if short_format == "sound":
        return "sound_short"
    if short_format == "silent":
        return "text_short"
    return "auto"


def _plan_production(
    client,
    model: str,
    script: str,
    context: str | None,
) -> ProducerPlan:
    context_block = (
        f"\nProduction context:\n{context.strip()}\n"
        if context and context.strip()
        else ""
    )
    prompt = f"""
You are FrameFusion's short-form video producer.

Script:
{script}
{context_block}

Choose exactly one format:
- sound_short for narrated shorts with ElevenLabs speech
- text_short for silent on-screen quote or caption videos

Return a concise rationale and any production limitations.
"""
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ProducerPlan,
            temperature=0,
        ),
    )
    return ProducerPlan.model_validate_json(response.text)


def run_producer_agent(
    script: str,
    context: str | None = None,
    short_format: ShortFormat = "auto",
    source_text: str | None = None,
) -> Dict[str, Any]:
    """Render a short video from a script."""
    normalized_script = " ".join(script.strip().split())
    if not normalized_script:
        raise ValueError("script must not be blank")

    try:
        client = get_gemini_client()
    except AgentConfigurationError as exc:
        raise ProducerAgentError(str(exc)) from exc

    model = get_gemini_model_name()
    produced_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    mapped_format = _map_short_format(short_format)
    naming_source = source_text or normalized_script
    if source_text is None and context and context.strip():
        naming_source = f"{normalized_script} {context.strip()}"
    resolved_output_name = resolve_output_name(
        naming_source,
        default_stem="short",
    )

    try:
        if mapped_format == "auto":
            plan = _plan_production(
                client=client,
                model=model,
                script=normalized_script,
                context=context,
            )
            selected_format = plan.short_format
            rationale = plan.rationale
            limitations = list(plan.limitations)
        elif mapped_format == "sound_short":
            selected_format = "sound_short"
            rationale = "Rendered as a narrated sound short."
            limitations = []
        else:
            selected_format = "text_short"
            rationale = "Rendered as a silent text short."
            limitations = []

        if selected_format == "text_short":
            video_result = produce_text_short_simple(
                normalized_script,
                resolved_output_name,
            )
        else:
            video_result = produce_sound_short_simple(
                normalized_script,
                resolved_output_name,
            )

        if selected_format == "sound_short" and not os.getenv("ELEVENLABS_API_KEY"):
            limitations.append("ElevenLabs narration requires ELEVENLABS_API_KEY.")
        limitations.append(
            "Background color and typography use FrameFusion defaults."
        )

        report = ProducerReport(
            script=normalized_script,
            produced_at=produced_at,
            short_format=selected_format,
            rationale=rationale,
            limitations=limitations,
            video=VideoProductionResult(**video_result),
            production_data={
                "requested_short_format": short_format,
                "selected_short_format": selected_format,
                "resolved_output_name": resolved_output_name,
                "video_result": video_result,
            },
        )
        return report.model_dump()
    except VideoProducerError as exc:
        raise ProducerAgentError(str(exc)) from exc
    except Exception as exc:
        raise ProducerAgentError(
            f"Producer agent failed: {exc}"
        ) from exc
