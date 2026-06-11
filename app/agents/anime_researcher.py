import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.models.anime import AnimeResearchReport
from app.models.history import HistoryCitation
from app.services.wikipedia_client import search_wikipedia


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


class AnimeAgentError(Exception):
    pass


def research_anime_tool(title: str, max_sources: int) -> str:
    """Finds Wikipedia source extracts for an anime title.

    Args:
        title: Anime title or franchise to research.
        max_sources: Number of relevant source articles, from 1 to 5.

    Returns:
        A JSON string containing article extracts and citation metadata.
    """
    return json.dumps(
        search_wikipedia(
            query=f"{title} anime",
            max_sources=max_sources,
            excluded_title_terms=("disambiguation",),
        )
    )


def research_anime(
    title: str,
    question: str = "Provide a factual, spoiler-light anime briefing.",
    max_sources: int = 3,
    allow_spoilers: bool = False,
) -> Dict[str, Any]:
    """Run the Gemini anime researcher and return a cited report."""
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise AnimeAgentError("GEMINI_API_KEY is not configured")

    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    client = genai.Client(api_key=api_key)
    researched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    spoiler_instruction = (
        "Spoilers are allowed, but label them clearly."
        if allow_spoilers
        else "Avoid major plot twists, endings, deaths, and hidden identities."
    )
    research_prompt = f"""
You are FrameFusion's anime research agent.

Anime title: {title}
User's question: {question}
Maximum sources: {max_sources}
Spoiler policy: {spoiler_instruction}

You must call research_anime_tool before answering. Base factual claims only on
the returned extracts and cite source numbers such as [1]. Do not invent episode
counts, release dates, studios, creators, adaptations, characters, awards, or
plot events. Distinguish sourced facts from thematic interpretation.

Prepare a concise research draft for short-form anime content.
"""

    try:
        research_response = client.models.generate_content(
            model=model,
            contents=research_prompt,
            config=types.GenerateContentConfig(
                tools=[research_anime_tool],
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="AUTO",
                    )
                ),
                temperature=0.2,
            ),
        )
        research_data = json.loads(research_anime_tool(title, max_sources))
        format_prompt = f"""
Convert the anime research below into the required response schema.

Requested title: {title}
Question: {question}
Spoiler policy: {spoiler_instruction}
Researched at UTC: {researched_at}
Research draft:
{research_response.text}

Authoritative source extracts:
{json.dumps(research_data)}

Requirements:
- Set source to "English Wikipedia via MediaWiki API".
- Include [number] source markers in factual items and the script.
- Build citations only from supplied source metadata.
- Keep the premise and script spoiler-light unless spoilers were allowed.
- Only name formats, dates, creators, studios, and adaptations when sourced.
- Themes may be interpretations, but phrase them cautiously.
- short_video_script should be approximately 60 to 120 words without
  production directions.
- State the active spoiler policy in spoiler_warning.
- Explain that Wikipedia is tertiary and specialist anime databases or
  official sources may contain more complete production details.
"""
        response = client.models.generate_content(
            model=model,
            contents=format_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=AnimeResearchReport,
                temperature=0,
            ),
        )
        report = AnimeResearchReport.model_validate_json(response.text)
        report.title = title.strip()
        report.researched_at = researched_at
        report.source = "English Wikipedia via MediaWiki API"
        report.research_data = research_data
        report.spoiler_warning = (
            "Spoilers allowed and should be clearly labeled."
            if allow_spoilers
            else "Spoiler-light: major plot developments are omitted."
        )
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
        raise AnimeAgentError(
            f"Anime research agent failed: {exc}"
        ) from exc
