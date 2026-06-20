import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

try:
    from moviepy import concatenate_videoclips
except ImportError:
    from moviepy.editor import concatenate_videoclips

from app.services.pexels_footage import PEXELS_CACHE_DIR, PexelsFootageError
from app.services.text_video_creator import VIDEO_SIZE, load_vertical_media_clip
from app.services.video_producer import GENERATED_DIR


class FootageStitcherError(Exception):
    pass


def _validate_output_name(output_name: str) -> str:
    normalized = output_name.strip()
    if (
        not normalized
        or normalized != normalized.split("/")[-1]
        or normalized != normalized.split("\\")[-1]
        or not normalized.lower().endswith(".mp4")
    ):
        raise ValueError("output_name must be an .mp4 filename without a path")
    return normalized


def _validate_clip_path(path: str) -> Path:
    resolved = Path(path).resolve()
    allowed_roots = {
        PEXELS_CACHE_DIR.resolve(),
        GENERATED_DIR.resolve(),
    }
    if not any(
        root == resolved or root in resolved.parents for root in allowed_roots
    ):
        raise ValueError("clip paths must come from downloaded Pexels footage")
    if not resolved.is_file():
        raise FileNotFoundError(f"Clip not found: {path}")
    return resolved


def _parse_clips_json(clips_json: str) -> List[Dict[str, str]]:
    try:
        payload = json.loads(clips_json)
    except json.JSONDecodeError as exc:
        raise ValueError("clips_json must be valid JSON") from exc

    if not isinstance(payload, list) or not payload:
        raise ValueError("clips_json must be a non-empty JSON array")

    clips: List[Dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("each clip entry must be an object")
        local_path = item.get("local_path")
        media_type = item.get("media_type")
        if not isinstance(local_path, str) or not isinstance(media_type, str):
            raise ValueError("each clip needs local_path and media_type")
        clips.append(
            {
                "local_path": str(_validate_clip_path(local_path)),
                "media_type": media_type,
            }
        )
    return clips


def _get_media_duration(path: str) -> float:
    try:
        from moviepy import VideoFileClip
    except ImportError:
        from moviepy.editor import VideoFileClip

    clip = VideoFileClip(path)
    try:
        return float(clip.duration)
    finally:
        clip.close()


def stitch_footage_clips(
    clips_json: str,
    output_name: str,
    seconds_per_clip: float,
) -> Dict[str, Any]:
    """Stitch downloaded Pexels clips into one vertical MP4."""
    validated_name = _validate_output_name(output_name)
    if seconds_per_clip < 1 or seconds_per_clip > 15:
        raise ValueError("seconds_per_clip must be between 1 and 15")

    clips = _parse_clips_json(clips_json)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = GENERATED_DIR / f"{uuid.uuid4().hex}_{validated_name}"

    composed_clips = []
    try:
        for clip_info in clips:
            composed_clips.append(
                load_vertical_media_clip(
                    clip_info["local_path"],
                    clip_info["media_type"],
                    seconds_per_clip,
                )
            )

        final_clip = concatenate_videoclips(composed_clips, method="compose")
        try:
            final_clip.write_videofile(
                str(output_path),
                codec="libx264",
                audio_codec="aac",
                fps=30,
                preset="medium",
                ffmpeg_params=[
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                ],
                logger=None,
            )
        finally:
            final_clip.close()
    except (OSError, ValueError) as exc:
        raise FootageStitcherError(str(exc)) from exc
    except Exception as exc:
        raise FootageStitcherError(
            f"Unable to stitch footage: {exc}"
        ) from exc
    finally:
        for clip in composed_clips:
            clip.close()

    if not output_path.is_file():
        raise FootageStitcherError("Stitched video file was not created")

    duration_seconds = _get_media_duration(str(output_path))
    return {
        "video_type": "footage_stitch",
        "output_path": str(output_path.resolve()),
        "output_name": validated_name,
        "width": VIDEO_SIZE[0],
        "height": VIDEO_SIZE[1],
        "duration_seconds": duration_seconds,
        "clip_count": len(clips),
        "seconds_per_clip": seconds_per_clip,
        "background_source": "Pexels",
    }
