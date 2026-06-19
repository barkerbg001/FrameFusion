import json
from datetime import datetime, timezone
from typing import Any, Dict

from google.genai import types

from app.agents.base import (
    AgentConfigurationError,
    get_gemini_client,
    get_gemini_model_name,
)
from app.models.screenwriter import ScreenwriterReport


class ScreenwriterAgentError(Exception):
    pass


def run_screenwriter_agent(
    task: str,
    context: str | None = None,
    research: Dict[str, Any] | None = None,
    target_words: int = 90,
    style: str = "short-form factual",
) -> Dict[str, Any]:
    """Write a short-form vertical video script from a task and optional research."""
    normalized_task = " ".join(task.strip().split())
    if len(normalized_task) < 5:
        raise ValueError("task must contain at least five characters")
    if target_words < 45 or target_words > 180:
        raise ValueError("target_words must be between 45 and 180")

    try:
        client = get_gemini_client()
    except AgentConfigurationError as exc:
        raise ScreenwriterAgentError(str(exc)) from exc

    model = get_gemini_model_name()
    written_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    context_block = (
        f"\nContext:\n{context.strip()}\n" if context and context.strip() else ""
    )
    if research:
        research_block = f"""
Research summary: {research.get("summary", "")}

Verified facts:
{json.dumps(research.get("verified_facts", []), indent=2)}

Content hooks:
{json.dumps(research.get("content_hooks", []), indent=2)}

Citations:
{json.dumps(research.get("citations", []), indent=2)}

Limitations:
{json.dumps(research.get("limitations", []), indent=2)}
"""
    else:
        research_block = "No prior research was supplied. Keep claims general."

    prompt = f"""
You are FrameFusion's screenwriter for vertical 9:16 short-form videos.

Task: {normalized_task}
Style: {style}
Target length: {target_words} words (acceptable range 60 to 120)
{context_block}
{research_block}

Write one speakable script suitable for on-screen text and/or narration.
Rules:
- Open with a strong hook in the first sentence.
- Use only facts supported by the research when research is provided.
- No scene directions, camera notes, markdown, labels, or speaker tags.
- No production directions such as "cut to" or "show b-roll".
- Keep the language punchy and social-native.
"""

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ScreenwriterReport,
                temperature=0.5,
            ),
        )
        report = ScreenwriterReport.model_validate_json(response.text)
        report.task = normalized_task
        report.written_at = written_at
        return report.model_dump()
    except ScreenwriterAgentError:
        raise
    except Exception as exc:
        raise ScreenwriterAgentError(
            f"Screenwriter agent failed: {exc}"
        ) from exc
