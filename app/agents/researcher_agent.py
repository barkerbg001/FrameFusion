import json
from datetime import datetime, timezone
from typing import Any, Dict

from google.genai import types

from app.agents.anime_researcher import research_anime
from app.agents.base import (
    AgentConfigurationError,
    get_current_time_tool,
    get_gemini_client,
    get_gemini_model_name,
    get_researchers_used,
    get_tool_results,
    get_tools_used,
    record_tool_result,
    reset_tool_results,
    search_pexels_tool,
)
from app.agents.history_researcher import research_history
from app.agents.pokemon_researcher import research_pokemon
from app.agents.weather_researcher import research_weather
from app.models.master import MasterResearchReport


class ResearcherAgentError(Exception):
    pass


def _delegate_researcher(
    tool_name: str,
    args: Dict[str, Any],
    action,
) -> str:
    try:
        result = action()
        record_tool_result(tool_name, args, result)
        return json.dumps(result)
    except Exception as exc:
        record_tool_result(tool_name, args, error=str(exc))
        return json.dumps({"error": str(exc)})


def research_weather_agent_tool(
    location: str,
    question: str,
    forecast_days: int,
) -> str:
    """Delegates to the weather research agent for a structured weather briefing.

    Args:
        location: City, region, or postal code to research.
        question: Specific weather question or briefing angle.
        forecast_days: Number of forecast days to retrieve, from 1 to 7.

    Returns:
        A JSON string with a structured weather research report.
    """
    args = {
        "location": location,
        "question": question,
        "forecast_days": forecast_days,
    }
    return _delegate_researcher(
        "weather_researcher",
        args,
        lambda: research_weather(
            location=location,
            question=question,
            forecast_days=forecast_days,
        ),
    )


def research_pokemon_agent_tool(identifier: str, question: str) -> str:
    """Delegates to the Pokemon research agent for verified PokeAPI facts.

    Args:
        identifier: Pokemon name or National Pokedex number.
        question: Specific Pokemon question or briefing angle.

    Returns:
        A JSON string with a structured Pokemon research report.
    """
    args = {"identifier": identifier, "question": question}
    return _delegate_researcher(
        "pokemon_researcher",
        args,
        lambda: research_pokemon(identifier=identifier, question=question),
    )


def research_history_agent_tool(
    topic: str,
    question: str,
    max_sources: int,
) -> str:
    """Delegates to the history research agent for cited historical briefings.

    Args:
        topic: Historical event, person, era, place, or question.
        question: Specific historical question or briefing angle.
        max_sources: Number of Wikipedia sources to retrieve, from 1 to 5.

    Returns:
        A JSON string with a structured history research report.
    """
    args = {
        "topic": topic,
        "question": question,
        "max_sources": max_sources,
    }
    return _delegate_researcher(
        "history_researcher",
        args,
        lambda: research_history(
            topic=topic,
            question=question,
            max_sources=max_sources,
        ),
    )


def research_anime_agent_tool(
    title: str,
    question: str,
    max_sources: int,
    allow_spoilers: bool,
) -> str:
    """Delegates to the anime research agent for cited anime briefings.

    Args:
        title: Anime title or franchise to research.
        question: Specific anime question or briefing angle.
        max_sources: Number of Wikipedia sources to retrieve, from 1 to 5.
        allow_spoilers: Whether major plot spoilers may be included.

    Returns:
        A JSON string with a structured anime research report.
    """
    args = {
        "title": title,
        "question": question,
        "max_sources": max_sources,
        "allow_spoilers": allow_spoilers,
    }
    return _delegate_researcher(
        "anime_researcher",
        args,
        lambda: research_anime(
            title=title,
            question=question,
            max_sources=max_sources,
            allow_spoilers=allow_spoilers,
        ),
    )


RESEARCHER_AGENT_TOOLS = [
    research_weather_agent_tool,
    research_pokemon_agent_tool,
    research_history_agent_tool,
    research_anime_agent_tool,
    get_current_time_tool,
    search_pexels_tool,
]


def run_researcher_agent(
    task: str,
    context: str | None = None,
) -> Dict[str, Any]:
    """Run the main researcher agent across domain specialists and utility tools."""
    normalized_task = " ".join(task.strip().split())
    if len(normalized_task) < 5:
        raise ValueError("task must contain at least five characters")

    try:
        client = get_gemini_client()
    except AgentConfigurationError as exc:
        raise ResearcherAgentError(str(exc)) from exc

    reset_tool_results()
    model = get_gemini_model_name()
    researched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    context_block = (
        f"\nAdditional context:\n{context.strip()}\n"
        if context and context.strip()
        else ""
    )
    research_prompt = f"""
You are FrameFusion's main research agent. You coordinate specialist researchers
and supporting tools to prepare factual briefings for short-form video creators.

Task: {normalized_task}
{context_block}
You can delegate to these specialist research agents:
- research_weather_agent_tool for weather briefings and forecasts
- research_pokemon_agent_tool for verified Pokemon facts
- research_history_agent_tool for cited historical topics
- research_anime_agent_tool for cited anime topics

You also have supporting tools:
- get_current_time_tool for local date and time context
- search_pexels_tool for royalty-free stock photos and b-roll videos

Call only the specialists and tools needed for this task. Prefer delegating
domain research to the matching specialist instead of guessing. When using
Pexels, note photographer credit requirements. Do not invent facts, URLs,
dates, statistics, or media that were not returned by a tool.

Prepare a concise research draft for a short-form content creator, including
factual findings, practical hooks, and visual or b-roll ideas when relevant.
"""

    try:
        research_response = client.models.generate_content(
            model=model,
            contents=research_prompt,
            config=types.GenerateContentConfig(
                tools=RESEARCHER_AGENT_TOOLS,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    maximum_remote_calls=8,
                ),
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="AUTO",
                    )
                ),
                temperature=0.2,
            ),
        )
        research_data = {"tool_calls": get_tool_results()}
        tools_used = get_tools_used()
        researchers_used = get_researchers_used()
        format_prompt = f"""
Convert the main researcher's findings below into the required response schema.

Task: {normalized_task}
Researched at UTC: {researched_at}
Researchers used: {", ".join(researchers_used) if researchers_used else "none"}
Tools used: {", ".join(tools_used) if tools_used else "none"}
Research draft:
{research_response.text}

Authoritative tool outputs:
{json.dumps(research_data)}

Requirements:
- Set task to the requested task text.
- Include only claims supported by the tool outputs above.
- verified_facts should be concise and independently useful.
- content_hooks should be factual hooks suitable for short-form videos.
- visual_suggestions should describe b-roll or on-screen visuals; prefer ideas
  grounded in Pexels results when available.
- recommended_media should list concrete photo or video picks from Pexels tool
  output when present; set download_url to the direct video_url or photo src URL,
  url to the Pexels page URL, and preview_url to the preview image when available;
  otherwise return an empty list.
- Build citations from Wikipedia source_number, title, and url values in any
  specialist report outputs.
- short_video_script should be approximately 60 to 120 words and must not
  include production directions.
- List each utility tool name once in tools_used.
- List each specialist agent name once in researchers_used.
- Explain missing data, tertiary-source limits, and attribution requirements in
  limitations.
- Preserve the exact tool call outputs in research_data.
"""
        response = client.models.generate_content(
            model=model,
            contents=format_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=MasterResearchReport,
                temperature=0,
            ),
        )
        report = MasterResearchReport.model_validate_json(response.text)
        report.task = normalized_task
        report.researched_at = researched_at
        report.tools_used = tools_used
        report.researchers_used = researchers_used
        report.research_data = research_data
        return report.model_dump()
    except ResearcherAgentError:
        raise
    except Exception as exc:
        raise ResearcherAgentError(
            f"Researcher agent failed: {exc}"
        ) from exc
