"""Bridge production-studio plans into the Editor render path."""

import json
from typing import Any, Dict, List, Literal

from app.services.footage_stitcher import stitch_footage_clips
from app.services.music_composer import compose_music
from app.services.pexels_footage import PexelsFootageError, download_pexels_clips
from app.services.video_audio import VideoAudioError, add_audio_file_to_video
from app.services.video_producer import DEFAULT_TEXT_COLOR


RenderMode = Literal["montage", "narrated", "text"]


def has_production_plans(
    cinematography: Dict[str, Any] | None,
    visual: Dict[str, Any] | None,
    voice: Dict[str, Any] | None,
    music_director: Dict[str, Any] | None,
    sound_design: Dict[str, Any] | None,
) -> bool:
    return any(
        plan is not None
        for plan in (
            cinematography,
            visual,
            voice,
            music_director,
            sound_design,
        )
    )


def format_production_plans_block(
    cinematography: Dict[str, Any] | None = None,
    visual: Dict[str, Any] | None = None,
    voice: Dict[str, Any] | None = None,
    music_director: Dict[str, Any] | None = None,
    sound_design: Dict[str, Any] | None = None,
) -> str:
    sections: List[str] = []
    if cinematography:
        sections.append(
            f"Cinematography shot list ({len(cinematography.get('shot_list', []))} shots):\n"
            f"{json.dumps(cinematography.get('shot_list', []), indent=2)}\n"
            f"Pacing: {cinematography.get('pacing_notes', '')}\n"
            f"Composition: {', '.join(cinematography.get('composition_notes', []))}"
        )
    if visual:
        sections.append(
            f"Visual style: {visual.get('visual_style', '')}\n"
            f"Color palette: {', '.join(visual.get('color_palette', []))}\n"
            f"Assets:\n{json.dumps(visual.get('assets', []), indent=2)}"
        )
    if voice:
        sections.append(
            f"Voice / narration: {voice.get('narration_approach', '')}\n"
            f"Voice style: {voice.get('voice_style', '')}\n"
            f"Delivery: {', '.join(voice.get('delivery_notes', []))}\n"
            f"Pacing: {voice.get('pacing', '')}"
        )
    if music_director:
        sections.append(
            f"Music style: {music_director.get('overall_style', '')}\n"
            f"Scene cues:\n{json.dumps(music_director.get('scene_cues', []), indent=2)}\n"
            f"Transitions: {music_director.get('transition_strategy', '')}"
        )
    if sound_design:
        sections.append(
            f"Ambient bed: {sound_design.get('ambient_bed', '')}\n"
            f"Sound layers:\n{json.dumps(sound_design.get('layers', []), indent=2)}\n"
            f"Mix notes: {', '.join(sound_design.get('mix_suggestions', []))}"
        )
    if not sections:
        return ""
    return "\n\nProduction studio plans (follow these closely):\n" + "\n\n".join(
        sections
    )


def primary_pexels_query(
    visual: Dict[str, Any] | None,
    cinematography: Dict[str, Any] | None,
    fallback: str,
) -> str:
    for asset in (visual or {}).get("assets", []):
        if not isinstance(asset, dict):
            continue
        query = " ".join(str(asset.get("search_query", "")).split())
        if len(query) >= 2:
            return query

    shots = (cinematography or {}).get("shot_list", [])
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        description = " ".join(str(shot.get("description", "")).split())
        if len(description) >= 2:
            return description

    return fallback


def colors_from_visual(
    visual: Dict[str, Any] | None,
    fallback_text: str = DEFAULT_TEXT_COLOR,
) -> tuple[str, str]:
    palette = (visual or {}).get("color_palette", [])
    background = ""
    text = fallback_text
    for color in palette:
        if not isinstance(color, str):
            continue
        normalized = color.strip().upper()
        if not normalized.startswith("#") or len(normalized) != 7:
            continue
        if not background:
            background = normalized
        elif text == fallback_text:
            text = normalized
    return background, text


def voice_prefers_narration(
    voice: Dict[str, Any] | None,
    short_format: str,
) -> bool:
    if short_format == "silent":
        return False
    if short_format == "sound":
        return True
    approach = (voice or {}).get("narration_approach", "").lower()
    if any(word in approach for word in ("silent", "text-only", "text only", "no narrat")):
        return False
    if any(word in approach for word in ("narrat", "voiceover", "voice-over", "spoken")):
        return True
    return True


def infer_render_mode(
    edit_brief: str,
    short_format: str,
    voice: Dict[str, Any] | None,
    cinematography: Dict[str, Any] | None,
) -> RenderMode:
    shots = (cinematography or {}).get("shot_list", []) if cinematography else []
    brief = edit_brief.lower()
    is_broll_brief = "b-roll" in brief or "broll" in brief or "montage" in brief

    if is_broll_brief and short_format != "sound":
        return "montage"
    if voice_prefers_narration(voice, short_format):
        return "narrated"
    if short_format == "silent":
        if len(shots) >= 2 or is_broll_brief:
            return "montage"
        return "text"
    if len(shots) >= 2 and (is_broll_brief or len(shots) >= 3):
        return "montage"
    if short_format == "sound":
        return "narrated"
    return "text"


def montage_seconds_per_clip(cinematography: Dict[str, Any] | None) -> float:
    shots = (cinematography or {}).get("shot_list", []) if cinematography else []
    if not shots:
        return 3.0
    durations = [
        float(shot.get("duration_seconds", 3))
        for shot in shots
        if isinstance(shot, dict)
    ]
    if not durations:
        return 3.0
    average = sum(durations) / len(durations)
    return max(1.0, min(15.0, average))


def _shot_query(
    shot: Dict[str, Any],
    visual: Dict[str, Any] | None,
    index: int,
    fallback: str,
) -> str:
    assets = (visual or {}).get("assets", [])
    pexels_queries = [
        " ".join(str(asset.get("search_query", "")).split())
        for asset in assets
        if isinstance(asset, dict) and asset.get("search_query")
    ]
    if index < len(pexels_queries) and len(pexels_queries[index]) >= 2:
        return pexels_queries[index]
    description = " ".join(str(shot.get("description", "")).split())
    return description if len(description) >= 2 else fallback


def build_cinematography_montage(
    edit_brief: str,
    output_name: str,
    cinematography: Dict[str, Any] | None,
    visual: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """Download and stitch clips guided by the cinematography shot list."""
    shots = (cinematography or {}).get("shot_list", [])[:6]
    if len(shots) < 2:
        shots = [{"description": edit_brief, "duration_seconds": 3}] * 4

    clip_entries: List[Dict[str, str]] = []
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            continue
        query = _shot_query(shot, visual, index, edit_brief)
        try:
            downloaded = download_pexels_clips(query, 1)
            clip_entries.extend(json.loads(downloaded["clips_json"]))
        except PexelsFootageError:
            continue

    if len(clip_entries) < 2:
        primary = primary_pexels_query(visual, cinematography, edit_brief)
        downloaded = download_pexels_clips(primary, min(len(shots), 6))
        clip_entries = json.loads(downloaded["clips_json"])

    seconds_per_clip = montage_seconds_per_clip(cinematography)
    stitched = stitch_footage_clips(
        json.dumps(clip_entries),
        output_name,
        seconds_per_clip,
    )
    stitched["render_mode"] = "montage"
    stitched["shot_count"] = len(clip_entries)
    stitched["seconds_per_clip"] = seconds_per_clip
    return stitched


def music_prompt_from_director(
    music_director: Dict[str, Any],
    sound_design: Dict[str, Any] | None,
    edit_brief: str,
) -> str:
    cues = music_director.get("scene_cues", [])
    if cues and isinstance(cues[0], dict):
        prompt = str(cues[0].get("music_prompt", "")).strip()
        if prompt:
            base = prompt
        else:
            base = music_director.get("overall_style", edit_brief)
    else:
        base = music_director.get("overall_style", edit_brief)

    ambient = (sound_design or {}).get("ambient_bed", "")
    if ambient:
        return f"{base}. Ambient layer: {ambient}"
    return base


def apply_production_music(
    video_result: Dict[str, Any],
    music_director: Dict[str, Any] | None,
    sound_design: Dict[str, Any] | None,
    edit_brief: str,
    output_name: str,
) -> Dict[str, Any]:
    """Generate score from Music Director plan and mux under the video."""
    if not music_director:
        return video_result

    prompt = music_prompt_from_director(music_director, sound_design, edit_brief)
    duration = int(video_result.get("duration_seconds", 30) or 30)
    duration = max(3, min(duration, 600))

    music = compose_music(
        prompt=prompt,
        duration_seconds=duration,
        force_instrumental=True,
    )
    scored_name = output_name.replace(".mp4", "-scored.mp4")
    if not scored_name.endswith(".mp4"):
        scored_name = f"{output_name.rsplit('.', 1)[0]}-scored.mp4"

    scored = add_audio_file_to_video(
        video_result["output_path"],
        scored_name,
        music["output_path"],
    )
    scored["render_mode"] = video_result.get("render_mode")
    scored["music_provider"] = music.get("provider")
    scored["music_prompt"] = prompt
    scored["scored_from"] = video_result.get("output_path")
    return scored


def should_score_with_music(
    render_mode: RenderMode,
    music_director: Dict[str, Any] | None,
    score_with_music: bool,
) -> bool:
    if not score_with_music or not music_director:
        return False
    return render_mode in {"montage", "text"}


def montage_edit_summary(
    cinematography: Dict[str, Any] | None,
    visual: Dict[str, Any] | None,
    clip_count: int,
    seconds_per_clip: float,
    scored: bool,
) -> str:
    shot_count = len((cinematography or {}).get("shot_list", []))
    style = (visual or {}).get("visual_style", "cinematic")
    summary = (
        f"Cut a {clip_count}-clip vertical montage from the cinematography shot list "
        f"({shot_count} planned shots, ~{seconds_per_clip:.1f}s per clip) "
        f"with {style} visual direction."
    )
    if scored:
        summary += " Music Director score muxed under the edit."
    return summary
