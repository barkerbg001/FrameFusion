import json
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
from app.agents.editor_production import (
    apply_production_music,
    build_cinematography_montage,
    colors_from_visual,
    format_production_plans_block,
    has_production_plans,
    infer_render_mode,
    montage_edit_summary,
    primary_pexels_query,
    should_score_with_music,
    voice_prefers_narration,
)
from app.models.producer import ShortFormat
from app.models.video_editor import VideoEditorReport
from app.models.video_tools import VideoProductionResult
from app.services.footage_stitcher import FootageStitcherError
from app.services.music_composer import MusicComposerError
from app.services.output_filename import resolve_output_name
from app.services.pexels_footage import PexelsFootageError, prepare_pexels_background
from app.services.video_audio import VideoAudioError
from app.services.video_producer import (
    DEFAULT_FONT_SIZE,
    DEFAULT_MODEL_ID,
    DEFAULT_TEXT_COLOR,
    VideoProducerError,
    estimate_text_short_duration,
    produce_sound_short,
    produce_text_short,
)


InternalFormat = Literal["text_short", "sound_short"]


class VideoEditorAgentError(Exception):
    pass


class EditorPlan(BaseModel):
    final_script: str
    short_format: InternalFormat
    pexels_query: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="Search query for royalty-free background footage",
    )
    background_color: str = Field(
        "",
        description="Optional #RRGGBB background when no Pexels media is used",
    )
    text_color: str = Field(DEFAULT_TEXT_COLOR)
    font_size: int = Field(DEFAULT_FONT_SIZE, ge=36, le=180)
    edit_summary: str
    visual_notes: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _map_short_format(short_format: str) -> str:
    if short_format == "sound":
        return "sound_short"
    if short_format == "silent":
        return "text_short"
    return "auto"


def _normalize_hex_color(value: str, fallback: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        return fallback
    if len(normalized) == 7 and normalized.startswith("#"):
        try:
            int(normalized[1:], 16)
            return normalized
        except ValueError:
            return fallback
    return fallback


def _plan_edits(
    client,
    model: str,
    edit_brief: str,
    script: str,
    context: str | None,
    research: Dict[str, Any] | None,
    source_production: Dict[str, Any] | None,
    production_block: str = "",
    preferred_format: InternalFormat | None = None,
    suggested_pexels_query: str | None = None,
) -> EditorPlan:
    context_block = (
        f"\nContext:\n{context.strip()}\n" if context and context.strip() else ""
    )
    research_block = (
        f"\nResearch:\n{json.dumps(research, indent=2)}\n" if research else ""
    )
    source_block = (
        f"\nPrior production:\n{json.dumps(source_production, indent=2)}\n"
        if source_production
        else ""
    )
    format_hint = ""
    if preferred_format == "sound_short":
        format_hint = "\nThe Voice Agent recommends narrated sound_short.\n"
    elif preferred_format == "text_short":
        format_hint = "\nThe Voice Agent recommends silent text_short.\n"
    query_hint = ""
    if suggested_pexels_query:
        query_hint = f"\nVisual Agent Pexels query to prefer: {suggested_pexels_query}\n"

    prompt = f"""
You are FrameFusion's video editor for vertical 9:16 short-form videos.

Edit brief:
{edit_brief}

Current script:
{script}
{context_block}{research_block}{source_block}{production_block}{format_hint}{query_hint}

Plan the editorial pass and final render settings:
- Tighten or rewrite the script for clarity, hooks, and speakability.
- Choose sound_short for narrated voice-over shorts or text_short for silent
  caption-style shorts.
- Honor cinematography pacing, visual style, and voice delivery when provided.
- Provide a concrete Pexels search query for background b-roll or imagery.
- Optionally set background_color and text_color as #RRGGBB values. Leave
  background_color blank to use random solid color when no Pexels clip applies.
- Keep final_script under 2500 characters with no markdown or stage directions.
- Summarize what changed in edit_summary and list visual_notes for the creator.
"""
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=EditorPlan,
            temperature=0.35,
        ),
    )
    return EditorPlan.model_validate_json(response.text)


def _render_montage_path(
    normalized_brief: str,
    resolved_output_name: str,
    cinematography: Dict[str, Any] | None,
    visual: Dict[str, Any] | None,
    music_director: Dict[str, Any] | None,
    sound_design: Dict[str, Any] | None,
    score_with_music: bool,
    limitations: list[str],
) -> tuple[Dict[str, Any], str, list[str], Literal["montage", "text_short"]]:
    try:
        video_result = build_cinematography_montage(
            edit_brief=normalized_brief,
            output_name=resolved_output_name,
            cinematography=cinematography,
            visual=visual,
        )
    except (PexelsFootageError, FootageStitcherError) as exc:
        raise VideoEditorAgentError(str(exc)) from exc

    visual_notes = list((visual or {}).get("assets", []))[:3]
    visual_note_strings = [
        item.get("description", "")
        for item in visual_notes
        if isinstance(item, dict) and item.get("description")
    ]
    scored = False
    if should_score_with_music("montage", music_director, score_with_music):
        try:
            video_result = apply_production_music(
                video_result=video_result,
                music_director=music_director,
                sound_design=sound_design,
                edit_brief=normalized_brief,
                output_name=resolved_output_name,
            )
            scored = True
            limitations.append(
                f"Background music generated ({video_result.get('music_provider', 'unknown')})."
            )
        except (MusicComposerError, VideoAudioError) as exc:
            limitations.append(f"Music scoring skipped: {exc}")

    edit_summary = montage_edit_summary(
        cinematography=cinematography,
        visual=visual,
        clip_count=int(video_result.get("shot_count", video_result.get("clip_count", 0))),
        seconds_per_clip=float(video_result.get("seconds_per_clip", 3)),
        scored=scored,
    )
    limitations.append(
        "Montage cut from cinematography shot list and Visual Agent Pexels queries."
    )
    return video_result, edit_summary, visual_note_strings, "text_short"


def run_video_editor_agent(
    edit_brief: str,
    script: str,
    context: str | None = None,
    research: Dict[str, Any] | None = None,
    source_production: Dict[str, Any] | None = None,
    short_format: ShortFormat = "auto",
    cinematography: Dict[str, Any] | None = None,
    visual: Dict[str, Any] | None = None,
    voice: Dict[str, Any] | None = None,
    music_director: Dict[str, Any] | None = None,
    sound_design: Dict[str, Any] | None = None,
    score_with_music: bool = True,
) -> Dict[str, Any]:
    """Plan editorial changes and render an updated short video."""
    normalized_brief = " ".join(edit_brief.strip().split())
    normalized_script = " ".join(script.strip().split())
    if len(normalized_brief) < 5:
        raise ValueError("edit_brief must contain at least five characters")
    if not normalized_script:
        raise ValueError("script must not be blank")

    try:
        client = get_gemini_client()
    except AgentConfigurationError as exc:
        raise VideoEditorAgentError(str(exc)) from exc

    model = get_gemini_model_name()
    edited_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    mapped_format = _map_short_format(short_format)
    naming_source = f"{normalized_brief} {normalized_script}"
    resolved_output_name = resolve_output_name(naming_source, default_stem="edited-short")
    production_block = format_production_plans_block(
        cinematography=cinematography,
        visual=visual,
        voice=voice,
        music_director=music_director,
        sound_design=sound_design,
    )
    using_production = has_production_plans(
        cinematography, visual, voice, music_director, sound_design
    )
    render_mode = infer_render_mode(
        normalized_brief,
        short_format,
        voice,
        cinematography,
    )

    try:
        limitations: list[str] = []
        if using_production and render_mode == "montage":
            video_result, edit_summary, visual_note_strings, selected_format = (
                _render_montage_path(
                    normalized_brief=normalized_brief,
                    resolved_output_name=resolved_output_name,
                    cinematography=cinematography,
                    visual=visual,
                    music_director=music_director,
                    sound_design=sound_design,
                    score_with_music=score_with_music,
                    limitations=limitations,
                )
            )
            final_script = normalized_script
            report = VideoEditorReport(
                edit_brief=normalized_brief,
                edited_at=edited_at,
                edit_summary=edit_summary,
                visual_notes=visual_note_strings,
                final_script=final_script,
                short_format=selected_format,
                rationale=edit_summary,
                limitations=limitations,
                video=VideoProductionResult(**video_result),
                edit_data={
                    "render_mode": "montage",
                    "requested_short_format": short_format,
                    "selected_short_format": selected_format,
                    "resolved_output_name": resolved_output_name,
                    "production_plans_applied": True,
                    "cinematography_shots": len(
                        (cinematography or {}).get("shot_list", [])
                    ),
                    "visual_style": (visual or {}).get("visual_style"),
                    "music_scored": bool(video_result.get("music_prompt")),
                    "music_prompt": video_result.get("music_prompt"),
                    "video_result": video_result,
                },
            )
            return report.model_dump()

        preferred_format: InternalFormat | None = None
        if using_production:
            preferred_format = (
                "sound_short"
                if voice_prefers_narration(voice, short_format)
                else "text_short"
            )
        suggested_query = primary_pexels_query(visual, cinematography, normalized_brief)

        plan = _plan_edits(
            client=client,
            model=model,
            edit_brief=normalized_brief,
            script=normalized_script,
            context=context,
            research=research,
            source_production=source_production,
            production_block=production_block,
            preferred_format=preferred_format,
            suggested_pexels_query=suggested_query,
        )
        selected_format = (
            mapped_format
            if mapped_format in ("text_short", "sound_short")
            else plan.short_format
        )
        if using_production and preferred_format:
            selected_format = preferred_format

        final_script = " ".join(plan.final_script.strip().split())
        if not final_script:
            raise VideoEditorAgentError("Editor plan returned an empty script")

        limitations = list(plan.limitations)
        pexels_query = suggested_query or plan.pexels_query
        pexels_background = None
        try:
            pexels_background = prepare_pexels_background(
                recommended_media=(
                    research.get("recommended_media") if research else None
                ),
                research_data=research.get("research_data") if research else None,
                fallback_query=pexels_query,
            )
        except PexelsFootageError as exc:
            limitations.append(f"Pexels background unavailable: {exc}")

        visual_bg, visual_text = colors_from_visual(visual, DEFAULT_TEXT_COLOR)
        background_color = _normalize_hex_color(
            plan.background_color or visual_bg,
            "",
        )
        text_color = _normalize_hex_color(
            plan.text_color or visual_text,
            DEFAULT_TEXT_COLOR,
        )

        if selected_format == "text_short":
            video_result = produce_text_short(
                text=final_script,
                duration_seconds=estimate_text_short_duration(final_script),
                background_color=background_color,
                text_color=text_color,
                font_size=plan.font_size,
                output_name=resolved_output_name,
                pexels_background=pexels_background,
            )
        else:
            video_result = produce_sound_short(
                text=final_script,
                voice_id="",
                model_id=DEFAULT_MODEL_ID,
                language_code="",
                background_color=background_color,
                text_color=text_color,
                font_size=plan.font_size,
                output_name=resolved_output_name,
                pexels_background=pexels_background,
            )

        if selected_format == "sound_short" and not os.getenv("ELEVENLABS_API_KEY"):
            limitations.append("ElevenLabs narration requires ELEVENLABS_API_KEY.")
        if pexels_background:
            photographer = pexels_background.get("photographer") or "Unknown"
            limitations.append(
                f"Background footage from Pexels by {photographer}. "
                "Credit the creator when publishing."
            )
        elif not background_color:
            limitations.append(
                "Background color and typography use FrameFusion defaults."
            )

        render_mode_label = "narrated" if selected_format == "sound_short" else "text"
        music_scored = False
        if should_score_with_music(
            "text" if selected_format == "text_short" else "narrated",
            music_director,
            score_with_music and selected_format == "text_short",
        ):
            try:
                video_result = apply_production_music(
                    video_result=video_result,
                    music_director=music_director,
                    sound_design=sound_design,
                    edit_brief=normalized_brief,
                    output_name=resolved_output_name,
                )
                music_scored = True
                limitations.append(
                    f"Background music from Music Director "
                    f"({video_result.get('music_provider', 'unknown')})."
                )
            except (MusicComposerError, VideoAudioError) as exc:
                limitations.append(f"Music scoring skipped: {exc}")

        if using_production:
            limitations.append(
                "Edit informed by cinematography, visual, and voice production plans."
            )

        report = VideoEditorReport(
            edit_brief=normalized_brief,
            edited_at=edited_at,
            edit_summary=plan.edit_summary,
            visual_notes=list(plan.visual_notes),
            final_script=final_script,
            short_format=selected_format,
            rationale=plan.edit_summary,
            limitations=limitations,
            video=VideoProductionResult(**video_result),
            edit_data={
                "render_mode": render_mode_label,
                "requested_short_format": short_format,
                "selected_short_format": selected_format,
                "resolved_output_name": resolved_output_name,
                "pexels_query": pexels_query,
                "pexels_background": pexels_background,
                "background_color": background_color or None,
                "text_color": text_color,
                "font_size": plan.font_size,
                "production_plans_applied": using_production,
                "visual_style": (visual or {}).get("visual_style"),
                "voice_style": (voice or {}).get("voice_style"),
                "music_scored": music_scored,
                "music_prompt": video_result.get("music_prompt"),
                "video_result": video_result,
            },
        )
        return report.model_dump()
    except VideoProducerError as exc:
        raise VideoEditorAgentError(str(exc)) from exc
    except VideoEditorAgentError:
        raise
    except Exception as exc:
        raise VideoEditorAgentError(
            f"Video editor agent failed: {exc}"
        ) from exc
