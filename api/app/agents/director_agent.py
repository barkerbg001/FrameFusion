import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote

from google.genai import types

from app.agents.base import (
    AgentConfigurationError,
    AUDIO_TOOLS,
    FOOTAGE_TOOLS,
    MUSIC_TOOLS,
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
from app.services.output_filename import resolve_output_name
from app.services.footage_stitcher import FootageStitcherError, stitch_footage_clips
from app.services.music_composer import MusicComposerError, compose_music
from app.services.pexels_footage import PexelsFootageError, download_pexels_clips
from app.services.video_audio import VideoAudioError, add_audio_file_to_video
from app.services.video_producer import VideoProducerError


class DirectorAgentError(Exception):
    pass


DIRECTOR_TOOLS = [
    *RESEARCH_TOOLS,
    *SHORT_VIDEO_TOOLS,
    *FOOTAGE_TOOLS,
    *AUDIO_TOOLS,
    *MUSIC_TOOLS,
]

SYSTEM_INSTRUCTION = """
You are Framey — FrameFusion's AI agent for short-form video creators.

You lead a production studio of specialist agents:
Director (vision), Producer (workflow), Research, Script, Cinematography,
Visual, Voice, Music Director, Sound Design, and Editor.

You coordinate research, scripting, music, and video production.

Research tools:
- get_weather_tool, get_pokemon_tool, search_wikipedia_tool
- get_current_time_tool, search_pexels_tool

Pexels b-roll tools (USE for multi-clip stock footage videos):
- download_pexels_footage_tool — search Pexels and download clips locally
- stitch_pexels_footage_tool — stitch downloaded clips into one 9:16 MP4
Workflow: download first, then stitch using the clips_json from the download result.

Audio tools (USE after a video exists):
- add_narration_to_video_tool — ElevenLabs voiceover behind an existing MP4
- add_audio_file_to_video_tool — mux an mp3/wav file behind an existing MP4
Pass the prior tool's output_path as video_path. For b-roll with voiceover:
download → stitch → add_narration_to_video_tool.

Music tools (USE when the user wants background music, a beat, or a soundtrack):
- generate_music_tool — creates instrumental background music (ElevenLabs when configured,
  otherwise a free procedural fallback). Pass the track's output_path to
  add_audio_file_to_video_tool to score an existing video.

Video creation tools (USE for narrated or text-on-screen shorts):
- create_text_short_video_tool — silent 9:16 vertical text videos (always available)
- create_sound_short_video_tool — narrated 9:16 videos with ElevenLabs voice

When the user asks for b-roll, stock footage, or a Pexels montage you MUST call
download_pexels_footage_tool and then stitch_pexels_footage_tool in the same turn
when possible. Do not only search Pexels and describe clips — download and stitch.

For silent b-roll montages (no narration or voiceover requested), add subtle
instrumental background music that matches the subject after stitching:
generate_music_tool → add_audio_file_to_video_tool using the stitch output_path.
Skip music only if the user asked for silent, no music, or no soundtrack.

When the user asks for a narrated/text short with one background clip, the editor
pipeline renders automatically with Pexels.

When the user asks to create, make, or render a video you MUST produce an MP4 in
the same turn. Do not only suggest editing tips.

Never say you will "delegate to the video editor" — you ARE Framey; pipelines and
tools run automatically. Never ask "would you like me to proceed?" after the user
already said yes — just create the video.

Never include file paths, output_path values, or local disk locations in replies.
When a video or track is ready, say "Preview or download it below."

Never say you cannot create video. You can always use create_text_short_video_tool.

Use tools instead of guessing facts. Be conversational and clear.
When you use tools, summarize results naturally rather than dumping raw JSON.
"""

BROLL_PATTERN = re.compile(
    r"\b(b[\s-]?roll|broll|pexels?|stock\s+footage|background\s+footage|"
    r"royalty[\s-]free\s+(video|footage|clip)s?)\b",
    re.IGNORECASE,
)

STITCH_PATTERN = re.compile(
    r"\b(stitch|montage|compile|combine|concatenate|multiple\s+clips?)\b",
    re.IGNORECASE,
)

PATH_PATTERN = re.compile(
    r"(?:[A-Za-z]:\\[^\s]*\.mp4|/[^\s]*\.mp4|(?:\./)?generated/[^\s]*\.mp4)",
    re.IGNORECASE,
)

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

NO_MUSIC_PATTERN = re.compile(
    r"\b(silent|no music|without music|no soundtrack|no audio|mute(d)?)\b",
    re.IGNORECASE,
)

MUSIC_PROMPT_STOPWORDS = re.compile(
    r"\b("
    r"generate|create|make|render|produce|build|a|an|the|"
    r"b[\s-]?roll|broll|video|montage|clip|clips|reel|short|"
    r"pexels?|stock\s+footage|footage|background"
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


def _conversation_text(messages: list[ChatMessage], limit: int = 12) -> str:
    return " ".join(message.content for message in messages[-limit:])


def _conversation_mentions_broll(messages: list[ChatMessage]) -> bool:
    return bool(BROLL_PATTERN.search(_conversation_text(messages)))


def _wants_footage_stitch(messages: list[ChatMessage]) -> bool:
    return bool(STITCH_PATTERN.search(_conversation_text(messages)))


def _wants_broll_montage(messages: list[ChatMessage]) -> bool:
    text = _conversation_text(messages)
    if not BROLL_PATTERN.search(text):
        return False
    if re.search(
        r"\b(narrat(ed|ion)|voiceover|voice[\s-]over|on[\s-]screen\s+text|script)\b",
        text,
        re.IGNORECASE,
    ):
        return False
    return True


def _wants_background_music(messages: list[ChatMessage]) -> bool:
    if NO_MUSIC_PATTERN.search(_conversation_text(messages)):
        return False
    return _wants_broll_montage(messages) or _wants_footage_stitch(messages)


def _derive_music_prompt(query: str) -> str:
    subject = MUSIC_PROMPT_STOPWORDS.sub(" ", query)
    subject = " ".join(subject.split()).strip(" ,.-")
    if len(subject) < 2:
        subject = "cinematic travel"
    return (
        f"Subtle instrumental background music for a {subject} b-roll montage, "
        "cinematic, atmospheric, no vocals"
    )


def _should_use_editor_pipeline(messages: list[ChatMessage]) -> bool:
    if _wants_footage_stitch(messages) or _wants_broll_montage(messages):
        return False
    last = messages[-1].content
    if BROLL_PATTERN.search(last):
        return True
    if not _conversation_mentions_broll(messages):
        return False
    if _user_wants_video_creation(messages):
        return True
    return bool(CONFIRMATION_PATTERN.search(last))


def _build_pipeline_task(messages: list[ChatMessage]) -> str:
    last = messages[-1].content.strip()
    broll_prefix = (
        "Create a polished short with Pexels b-roll background footage. "
        if _conversation_mentions_broll(messages)
        else ""
    )

    if CONFIRMATION_PATTERN.search(last) and len(last) <= 40:
        for message in reversed(messages[:-1]):
            if message.role == "user" and len(message.content.strip()) > 15:
                if not CONFIRMATION_PATTERN.search(message.content):
                    return broll_prefix + message.content.strip()
        return (
            f"{broll_prefix}Fulfill the latest video request from this conversation."
        )

    return broll_prefix + last


def _sanitize_reply(text: str, has_attachments: bool) -> str:
    cleaned = PATH_PATTERN.sub("", text)
    cleaned = re.sub(
        r"You can (?:find|watch|view|download)(?: the (?:video|track|audio))?\s*here:\s*",
        "Preview or download it below. ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if has_attachments and "below" not in cleaned.lower():
        cleaned = f"{cleaned}\n\nPreview or download it below.".strip()
    return cleaned or (
        "Preview or download it below." if has_attachments else cleaned
    )


def _user_wants_video_creation(messages: list[ChatMessage]) -> bool:
    last = messages[-1].content
    if VIDEO_INTENT_PATTERN.search(last):
        return True

    if not CONFIRMATION_PATTERN.search(last):
        return False

    recent = " ".join(message.content for message in messages[-8:])
    return bool(
        re.search(
            r"\b(video|short|mp4|reel|clip|b[\s-]?roll|broll|pexels?)\b",
            recent,
            re.IGNORECASE,
        )
    )


def _format_conversation(messages: list[ChatMessage], limit: int = 12) -> str:
    lines: list[str] = []
    for message in messages[-limit:]:
        speaker = "User" if message.role == "user" else "Framey"
        lines.append(f"{speaker}: {message.content}")
    return "\n\n".join(lines)


def _extract_attachments() -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    seen: set[str] = set()
    superseded_videos: set[str] = set()

    for entry in get_tool_results():
        if entry.get("tool") != "video_audio":
            continue
        result = entry.get("result")
        if not isinstance(result, dict):
            continue
        source_video = result.get("source_video_path")
        if isinstance(source_video, str):
            superseded_videos.add(Path(source_video).name)

    for entry in get_tool_results():
        if entry.get("tool") not in (
            "text_short",
            "sound_short",
            "footage_stitch",
            "video_audio",
            "music",
        ):
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
        if entry.get("tool") == "footage_stitch" and file_name in superseded_videos:
            continue
        if entry.get("tool") == "music":
            has_scored_video = any(
                other.get("tool") == "video_audio"
                for other in get_tool_results()
            )
            if has_scored_video:
                continue
        seen.add(file_name)

        if entry.get("tool") == "music" or result.get("audio_type") == "music":
            attachments.append(
                {
                    "type": "audio",
                    "url": f"/api/chat/audio/{quote(file_name)}",
                    "filename": str(result.get("output_name", file_name)),
                    "duration_seconds": result.get("duration_seconds"),
                }
            )
            continue

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
        task=_build_pipeline_task(messages),
        context=f"Conversation so far:\n{conversation}",
        produce_short=True,
        short_format="auto",
    )
    production = pipeline.get("production")
    if not isinstance(production, dict):
        raise DirectorAgentError("Pipeline did not produce a video")

    _record_pipeline_production(production)
    message = _pipeline_fallback_message(production)
    edit_data = production.get("edit_data") or {}
    if edit_data.get("pexels_background"):
        message += " Includes Pexels b-roll background footage."
    return message


def _derive_footage_query(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role != "user":
            continue
        content = message.content.strip()
        if len(content) < 8:
            continue
        if CONFIRMATION_PATTERN.search(content) and len(content) <= 40:
            continue
        return content
    return "motivational nature b-roll"


def _run_footage_stitch_fallback(messages: list[ChatMessage]) -> str:
    query = _derive_footage_query(messages)
    downloaded = download_pexels_clips(query, 4)
    record_tool_result(
        "pexels_download",
        {"query": query, "clip_count": 4},
        downloaded,
    )
    output_name = resolve_output_name(query, default_stem="broll-montage")
    stitched = stitch_footage_clips(downloaded["clips_json"], output_name, 3.0)
    clip_count = downloaded["clip_count"]
    base_message = (
        f"Your Pexels b-roll montage is ready ({clip_count} clips). "
    )

    if _wants_background_music(messages):
        scored_name = f"{Path(output_name).stem}-scored.mp4"
        music_prompt = _derive_music_prompt(query)
        duration = int(stitched.get("duration_seconds", 12) or 12)
        try:
            music = compose_music(
                prompt=music_prompt,
                duration_seconds=max(3, min(duration, 180)),
                force_instrumental=True,
            )
            scored = add_audio_file_to_video(
                stitched["output_path"],
                scored_name,
                music["output_path"],
            )
            record_tool_result(
                "video_audio",
                {
                    "video_path": stitched["output_path"],
                    "output_name": scored_name,
                    "audio_path": music["output_path"],
                },
                scored,
            )
            return (
                f"{base_message}Added subtle background music to match the vibe. "
                "Preview or download below."
            )
        except (MusicComposerError, VideoAudioError, OSError) as exc:
            record_tool_result(
                "footage_stitch",
                {
                    "clips_json": downloaded["clips_json"],
                    "output_name": output_name,
                    "seconds_per_clip": 3,
                },
                stitched,
            )
            return (
                f"{base_message}Preview or download below. "
                f"(Background music unavailable: {exc})"
            )

    record_tool_result(
        "footage_stitch",
        {
            "clips_json": downloaded["clips_json"],
            "output_name": output_name,
            "seconds_per_clip": 3,
        },
        stitched,
    )
    return f"{base_message}Preview or download below."


def run_director_chat(messages: list[ChatMessage]) -> DirectorChatResult:
    if messages[-1].role != "user":
        raise ValueError("The last message must be from the user")

    wants_video = _user_wants_video_creation(messages)
    use_editor = _should_use_editor_pipeline(messages)
    wants_broll_montage = _wants_broll_montage(messages)

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
    if use_editor:
        system_instruction += (
            "\n\nThe user wants a narrated/text short with Pexels background. Do NOT "
            "call create_text_short_video_tool or create_sound_short_video_tool — "
            "the editor pipeline renders with Pexels automatically. You may use "
            "research tools. Keep your reply brief."
        )
    elif _wants_footage_stitch(messages) or wants_broll_montage:
        music_note = (
            " After stitching, call generate_music_tool then "
            "add_audio_file_to_video_tool for subtle instrumental background music "
            "that matches the subject."
            if _wants_background_music(messages)
            else ""
        )
        system_instruction += (
            "\n\nThe user wants a Pexels b-roll montage. You MUST call "
            "download_pexels_footage_tool and then stitch_pexels_footage_tool "
            f"using the clips_json from the download result before finishing.{music_note}"
        )
    elif wants_video:
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
    attachments = _extract_attachments()

    if use_editor:
        reset_tool_results()
        try:
            fallback_note = _run_pipeline_fallback(messages)
            attachments = _extract_attachments()
            if attachments:
                reply = (
                    f"{reply}\n\n{fallback_note}".strip()
                    if reply
                    else fallback_note
                )
        except (DirectorAgentError, VideoEditorAgentError, VideoProducerError) as exc:
            error_note = (
                f"I tried to render the video with Pexels b-roll but it failed: {exc}"
            )
            reply = f"{reply}\n\n{error_note}".strip() if reply else error_note
    elif (wants_broll_montage or _wants_footage_stitch(messages)) and not attachments:
        reset_tool_results()
        try:
            fallback_note = _run_footage_stitch_fallback(messages)
            attachments = _extract_attachments()
            if attachments:
                reply = (
                    f"{reply}\n\n{fallback_note}".strip()
                    if reply
                    else fallback_note
                )
        except (PexelsFootageError, FootageStitcherError, DirectorAgentError) as exc:
            error_note = f"I tried to build the Pexels b-roll montage but it failed: {exc}"
            reply = f"{reply}\n\n{error_note}".strip() if reply else error_note
    elif wants_video and not attachments and not wants_broll_montage:
        try:
            fallback_note = _run_pipeline_fallback(messages)
            attachments = _extract_attachments()
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

    reply = _sanitize_reply(reply, bool(attachments))
    return DirectorChatResult(content=reply, attachments=attachments)
