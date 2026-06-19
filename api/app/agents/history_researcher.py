import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.models.history import HistoryCitation, HistoryResearchReport
from app.services.history_client import research_history_sources


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


class HistoryAgentError(Exception):
    pass


def research_history_tool(topic: str, max_sources: int) -> str:
    """Finds historical source extracts and citation URLs.

    Args:
        topic: Historical event, person, era, place, or question to research.
        max_sources: Number of relevant source articles to retrieve, from 1 to 5.

    Returns:
        A JSON string containing source extracts and citation metadata.
    """
    return json.dumps(research_history_sources(topic, max_sources))


def research_history(
    topic: str,
    question: str = "Provide a concise, factual historical briefing.",
    max_sources: int = 3,
) -> Dict[str, Any]:
    """Run the Gemini history researcher and return a cited report."""
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HistoryAgentError("GEMINI_API_KEY is not configured")

    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    client = genai.Client(api_key=api_key)
    researched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    research_prompt = f"""
You are FrameFusion's history research agent.

Topic: {topic}
User's question: {question}
Maximum sources: {max_sources}

You must call research_history_tool before answering. Base factual claims only
on the returned source extracts. Refer to evidence with source numbers such as
[1] and [2]. Do not invent dates, quotations, people, causes, or consequences.
If the sources disagree or do not answer part of the question, state that
clearly. Distinguish documented facts from interpretation.

Prepare a concise research draft for a short-form educational content creator.
"""

    try:
        research_response = client.models.generate_content(
            model=model,
            contents=research_prompt,
            config=types.GenerateContentConfig(
                tools=[research_history_tool],
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="AUTO",
                    )
                ),
                temperature=0.2,
            ),
        )
        research_data = json.loads(
            research_history_tool(topic, max_sources)
        )
        format_prompt = f"""
Convert the historical research below into the required response schema.

Topic: {topic}
Question: {question}
Researched at UTC: {researched_at}
Research draft:
{research_response.text}

Authoritative source extracts:
{json.dumps(research_data)}

Requirements:
- Set source to "English Wikipedia via MediaWiki API".
- Include source markers like [1] in factual list items and the script.
- Build citations only from the supplied source_number, title, and url values.
- Keep timeline entries chronological where dates are available.
- Use empty lists where the extracts do not establish people, causes,
  consequences, or uncertainties.
- short_video_script should be approximately 60 to 120 words and must not
  include production directions.
- State that Wikipedia is a tertiary source and that important claims should
  be checked against primary or scholarly sources.
"""
        response = client.models.generate_content(
            model=model,
            contents=format_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=HistoryResearchReport,
                temperature=0,
            ),
        )
        report = HistoryResearchReport.model_validate_json(response.text)
        report.topic = topic.strip()
        report.researched_at = researched_at
        report.source = "English Wikipedia via MediaWiki API"
        report.research_data = research_data
        report.citations = [
            HistoryCitation(
                source_number=source["source_number"],
                title=source["title"],
                url=source["url"],
            )
            for source in research_data["sources"]
        ]
        return report.model_dump()
    except Exception as exc:
        raise HistoryAgentError(
            f"History research agent failed: {exc}"
        ) from exc
