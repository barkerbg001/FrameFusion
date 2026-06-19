import json
from datetime import datetime, timezone
from typing import Any, Dict

from google.genai import types

from app.agents.base import (
    AgentConfigurationError,
    RESEARCH_TOOLS,
    get_gemini_client,
    get_gemini_model_name,
    get_tool_results,
    get_tools_used,
    reset_tool_results,
)
from app.models.research import ResearchReport


class ResearcherAgentError(Exception):
    pass


UNIFIED_RESEARCH_TOOLS = RESEARCH_TOOLS


def run_researcher_agent(
    task: str,
    context: str | None = None,
) -> Dict[str, Any]:
    """Run the unified research agent across weather, Pokemon, Wikipedia, and Pexels."""
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
You are FrameFusion's unified research agent for short-form video creators.
You handle every research domain directly — weather, Pokemon, history, anime,
current events, and general topics — using your tools.

Task: {normalized_task}
{context_block}
Available tools:
- get_weather_tool for current conditions and multi-day forecasts
- get_pokemon_tool for verified PokeAPI Pokemon data
- search_wikipedia_tool for cited article extracts on history, anime, people,
  events, and general knowledge
- get_current_time_tool for local date and time context
- search_pexels_tool for royalty-free stock photos and b-roll videos

Call only the tools needed for this task. Do not invent facts, URLs, dates,
statistics, or media that were not returned by a tool. When using Pexels, note
photographer credit requirements.

Prepare a concise factual research draft including verified findings, hooks,
and visual or b-roll ideas. Do not write the final video script — a screenwriter
handles that separately.
"""

    try:
        research_response = client.models.generate_content(
            model=model,
            contents=research_prompt,
            config=types.GenerateContentConfig(
                tools=UNIFIED_RESEARCH_TOOLS,
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
        format_prompt = f"""
Convert the research findings below into the required response schema.

Task: {normalized_task}
Researched at UTC: {researched_at}
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
- Build citations from Wikipedia source_number, title, and url values when present.
- Explain missing data, tertiary-source limits, and attribution requirements in
  limitations.
- Preserve the exact tool call outputs in research_data.
- Do not include a video script field.
"""
        response = client.models.generate_content(
            model=model,
            contents=format_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ResearchReport,
                temperature=0,
            ),
        )
        report = ResearchReport.model_validate_json(response.text)
        report.task = normalized_task
        report.researched_at = researched_at
        report.tools_used = tools_used
        report.research_data = research_data
        return report.model_dump()
    except ResearcherAgentError:
        raise
    except Exception as exc:
        raise ResearcherAgentError(
            f"Researcher agent failed: {exc}"
        ) from exc
