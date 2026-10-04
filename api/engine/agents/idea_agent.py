from datetime import UTC, datetime
from typing import Any, Dict

from engine.agents.base import (
    AgentConfigurationError,
    get_current_time_tool,
    get_llm_client,
    get_llm_model_name,
    get_tools_used,
    reset_tool_results,
    search_pexels_tool,
)
from engine.agents.response_schema import generate_validated
from engine.llm import types
from engine.schemas.idea import IdeaDraft, IdeaReport


class IdeaAgentError(Exception):
    pass


IDEA_AGENT_TOOLS = [
    get_current_time_tool,
    search_pexels_tool,
]


def run_idea_agent(
    topic: str,
    context: str | None = None,
    audience: str | None = None,
    idea_count: int = 5,
) -> Dict[str, Any]:
    """Brainstorm short-form video ideas for a topic or niche."""
    normalized_topic = " ".join(topic.strip().split())
    if len(normalized_topic) < 3:
        raise ValueError("topic must contain at least three characters")
    if idea_count < 1 or idea_count > 10:
        raise ValueError("idea_count must be between 1 and 10")

    try:
        client = get_llm_client("ideas")
    except AgentConfigurationError as exc:
        raise IdeaAgentError(str(exc)) from exc

    reset_tool_results()
    model = get_llm_model_name("ideas")
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    context_block = (
        f"\nAdditional context:\n{context.strip()}\n" if context and context.strip() else ""
    )
    audience_block = (
        f"\nTarget audience:\n{audience.strip()}\n" if audience and audience.strip() else ""
    )
    prompt = f"""
You are FrameFusion's idea agent for vertical short-form videos.

Topic or niche: {normalized_topic}
{context_block}{audience_block}
Generate exactly {idea_count} distinct short-form video ideas.

You may use:
- get_current_time_tool for timely or seasonal angles
- search_pexels_tool to check whether strong b-roll exists for visual ideas

Each idea should be practical for a research-and-produce pipeline:
- sound_short fits narrated explainers and briefings
- silent fits quote-style or caption-led posts
- auto when either format could work

For every idea:
- title should be short and channel-ready
- hook should grab attention in the first two seconds
- concept should explain the video in two or three sentences
- research_task must be a complete instruction another agent can execute,
  such as "Create a weather briefing short about Johannesburg this week"
- visual_angle should describe b-roll or on-screen visuals
- why_it_works should explain audience appeal briefly

Prefer varied angles across the set. Do not repeat the same premise.
Do not invent facts, statistics, or events. Mark speculative angles clearly
in limitations when relevant.
"""

    try:
        brainstorm = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=IDEA_AGENT_TOOLS,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    maximum_remote_calls=6,
                ),
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="AUTO",
                    )
                ),
                temperature=0.7,
            ),
        )
        tools_used = get_tools_used()
        format_prompt = f"""
Convert the brainstorming notes below into the required JSON object.

Topic: {normalized_topic}
Brainstorming notes:
{brainstorm.text}

Requirements:
- summary: one or two sentences describing the set of ideas.
- Return exactly {idea_count} ideas unless fewer strong distinct ideas exist.
- research_task on each idea must be a complete instruction the orchestrator can act on.
- suggested_format must be one of: auto, narrated, silent, text_short, sound_short.
- Explain speculative or unverified angles in limitations.
"""
        draft = generate_validated(
            client, format_prompt, IdeaDraft, temperature=0, model_name=model
        )
        report = IdeaReport(
            topic=normalized_topic,
            generated_at=generated_at,
            summary=draft.summary
            or f"{len(draft.ideas)} short-video ideas about {normalized_topic}.",
            ideas=draft.ideas,
            tools_used=tools_used,
            limitations=draft.limitations
            or ["Ideas are creative starting points and should be verified during research."],
        )
        return report.model_dump()
    except IdeaAgentError:
        raise
    except Exception as exc:
        raise IdeaAgentError(f"Idea agent failed: {exc}") from exc
