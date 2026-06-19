import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote

from google.genai import types

from app.agents.base import (
    AgentConfigurationError,
    RESEARCH_TOOLS,
    SHORT_VIDEO_TOOLS,
    get_gemini_client,
    get_gemini_model_name,
    get_tool_results,
    record_tool_result,
    reset_tool_results,
)
from app.agents.researcher_agent import ResearcherAgentError, run_researcher_agent
from app.agents.screenwriter_agent import ScreenwriterAgentError, run_screenwriter_agent
from app.agents.video_editor_agent import VideoEditorAgentError, run_video_editor_agent
from app.models.chat import ChatMessage
from app.services.video_producer import VideoProducerError


class DirectorAgentError(Exception):
    pass


DIRECTOR_TOOLS = [*RESEARCH_TOOLS, *SHORT_VIDEO_TOOLS]

SYSTEM_INSTRUCTION = """
You are Frammy — FrameFusion's director for short-form video creators.

You coordinate research, scripting, and video production. Refer to yourself as Frammy
when speaking to the user. You have direct tools for quick lookups and one-off renders,
and you delegate full pipeline work to specialist agents (researcher, screenwriter,
video editor) when needed.

Research tools:
- get_weather_tool, get_pokemon_tool, search_wikipedia_tool
- get_current_time_tool, search_pexels_tool

Video creation tools (USE THESE when the user wants an actual video file):
- create_text_short_video_tool — silent 9:16 vertical text videos (always available)
- create_sound_short_video_tool — narrated 9:16 videos with ElevenLabs voice

When the user asks to create, make, or render a video you MUST call a video tool
in the same turn. Do not only suggest Pexels clips, editing tips, or B-roll —
produce the MP4 file first, then briefly summarize what you made.

For research-heavy or polished shorts, gather facts first. The full pipeline is
research → screenwriter → video editor; chat fallback runs that automatically.

Never say you cannot create video. You can always use create_text_short_video_tool.

Use tools instead of guessing facts. Be conversational and clear.
When you use tools, summarize results naturally rather than dumping raw JSON.
"""

VIDEO_INTENT_PATTERN = re.compile(
    r"\b(create|make|generate|render|produce|build)\b.{0,48}\b("
    r"video|short|clip|reel)\b|\b(video|short)\b.{0,48}\b(on|about|for)\b",
    re.IGNORECASE,
)

CONFIRMATION_PATTERN = re.compile(
    r"\b("
    r"yes|please|do it|go ahead|sounds good|let's do|lets do|"
    r"do what you think is best|create the video|make the video|"
    r"create it|make it|go for it"
    r")\b",
    re.IGNORECASE,
)


@dataclass
class DirectorChatResult:
    content: str
    attachments: list[dict[str, Any]] = field(default_factory=list)


def run_director_pipeline(
    task: str,
    context: str | None = None,
    produce_short: bool = True,
    short_format: str = "auto",
) -> Dict[str, Any]:
    """Research, screenwrite, edit, then optionally render a short video."""
    try:
        research = run_researcher_agent(task=task, context=context)
        script = run_screenwriter_agent(
            task=task,
            context=context,
            research=research,
        )
        result = {
            **research,
            "short_video_script": script["short_video_script"],
            "researchers_used": [],
            "screenwriter": script,
        }
        result["production"] = None
        if produce_short:
            try:
                result["production"] = run_video_editor_agent(
                    edit_brief=task,
                    script=script["short_video_script"],
                    context=context,
                    research=research,
                    short_format=short_format,
                )
            except VideoEditorAgentError as exc:
                raise DirectorAgentError(
                    f"Video editing failed: {exc}"
                 ) from exc
        return result
    except ResearcherAgentError as exc:
        raise DirectorAgentError(str(exc)) from exc
    except ScreenwriterAgentError as exc:
        raise DirectorAgentError(str(exc)) from exc
    except DirectorAgentError:
        raise
    except Exception as exc:
        raise DirectorAgentError(
            f"Director agent failed: {exc}"
        ) from exc


def _user_wants_video_creation(messages: list[ChatMessage]) -> bool:
    last = messages[-1].content
    if VIDEO_INTENT_PATTERN.search(last):
        return True

    if not CONFIRMATION_PATTERN.search(last):
        return False

    recent = " ".join(message.content for message in messages[-8:])
    return bool(re.search(r"\b(video|short|mp4|reel|clip)\b", recent, re.IGNORECASE))


def _format_conversation(messages: list[ChatMessage], limit: int = 12) -> str:
    lines: list[str] = []
    for message in messages[-limit:]:
        speaker = "User" if message.role == "user" else "Frammy"
        lines.append(f"{speaker}: {message.content}")
    return "\n\n".join(lines)


def _extract_video_attachments() -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    seen: set[str] = set()

    for entry in get_tool_results():
        if entry.get("tool") not in ("text_short", "sound_short"):
            continue
        result = entry.get("result")
        if not isinstance(result, dict):
            continue
        output_path = result.get("output_path")
        if not isinstance(output_path, str):
            continue

        file_name = Path(output_path).name
        if file_name in seen:
            continue
        seen.add(file_name)

        attachments.append(
            {
                "type": "video",
                "url": f"/api/chat/videos/{quote(file_name)}",
                "filename": str(result.get("output_name", file_name)),
                "duration_seconds": result.get("duration_seconds"),
            }
        )

    return attachments


def _record_pipeline_production(production: Dict[str, Any]) -> None:
    record_tool_result(
        production["short_format"],
        {
            "text": production["final_script"],
            "output_name": production["video"]["output_name"],
        },
        production["video"],
    )


def _pipeline_fallback_message(production: Dict[str, Any]) -> str:
    edit_summary = production.get("edit_summary", "Your video is ready.")
    if production.get("short_format") == "sound_short":
        return f"{edit_summary} Preview or download your narrated video below."
    return (
        f"{edit_summary} Preview or download your text short below. "
        "(Add ELEVENLABS_API_KEY for narrated videos.)"
    )


def _run_pipeline_fallback(messages: list[ChatMessage]) -> str:
    conversation = _format_conversation(messages)
    pipeline = run_director_pipeline(
        task=messages[-1].content,
        context=f"Conversation so far:\n{conversation}",
        produce_short=True,
        short_format="auto",
    )
    production = pipeline.get("production")
    if not isinstance(production, dict):
        raise DirectorAgentError("Pipeline did not produce a video")

    _record_pipeline_production(production)
    return _pipeline_fallback_message(production)


def run_director_chat(messages: list[ChatMessage]) -> DirectorChatResult:
    if messages[-1].role != "user":
        raise ValueError("The last message must be from the user")

    wants_video = _user_wants_video_creation(messages)

    try:
        client = get_gemini_client()
    except AgentConfigurationError as exc:
        raise DirectorAgentError(str(exc)) from exc

    reset_tool_results()
    model = get_gemini_model_name()
    contents = [
        types.Content(
            role="user" if message.role == "user" else "model",
            parts=[types.Part(text=message.content)],
        )
        for message in messages
    ]

    system_instruction = SYSTEM_INSTRUCTION
    if wants_video:
        system_instruction += (
            "\n\nThe user's latest message is a video creation request. "
            "You must call create_sound_short_video_tool or "
            "create_text_short_video_tool before finishing your reply."
        )

    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=DIRECTOR_TOOLS,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    maximum_remote_calls=16,
                ),
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="AUTO",
                    )
                ),
                temperature=0.4,
            ),
        )
    except DirectorAgentError:
        raise
    except Exception as exc:
        raise DirectorAgentError(f"Director chat failed: {exc}") from exc

    reply = (response.text or "").strip()
    attachments = _extract_video_attachments()

    if wants_video and not attachments:
        try:
            fallback_note = _run_pipeline_fallback(messages)
            attachments = _extract_video_attachments()
            if attachments:
                reply = (
                    f"{reply}\n\n{fallback_note}".strip()
                    if reply
                    else fallback_note
                )
        except (DirectorAgentError, VideoEditorAgentError, VideoProducerError) as exc:
            error_note = f"I tried to render the video but it failed: {exc}"
            reply = f"{reply}\n\n{error_note}".strip() if reply else error_note

    if not reply and attachments:
        count = len(attachments)
        reply = (
            f"Done — I created {count} video{'s' if count != 1 else ''} for you. "
            "Preview or download below."
        )
    elif not reply:
        raise DirectorAgentError("The agent returned an empty response")

    return DirectorChatResult(content=reply, attachments=attachments)
