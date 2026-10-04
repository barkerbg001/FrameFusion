"""Render jobs for the direct video tools (no LLM involved)."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from django.conf import settings

from engine.paths import GENERATED_DIR
from engine.runtime import check_cancelled, report
from studio.jobs import register
from studio.media import asset_payload, register_asset
from studio.models import GenerationJob


def upload_dir(job_id: uuid.UUID | str) -> Path:
    path = Path(settings.FRAMEFUSION_UPLOAD_DIR) / str(job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _output_path(output_name: str) -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    return GENERATED_DIR / f"{uuid.uuid4().hex}_{output_name}"


def _finish(job: GenerationJob, path: Path, extra: dict[str, Any]) -> dict[str, Any]:
    asset = register_asset(path.name, project=job.project, job=job)
    media = [asset_payload(asset)] if asset else []
    return {"report": {**extra, "output_name": path.name}, "media": media}


def _text_video(job: GenerationJob, data: dict[str, Any]) -> dict[str, Any]:
    from engine.services.text_video_creator import create_text_short

    path = _output_path(data["output_name"])
    create_text_short(
        text=data["text"],
        output_path=str(path),
        duration_seconds=data["duration_seconds"],
        background_color=data.get("background_color"),
        text_color=data["text_color"],
        font_size=data["font_size"],
    )
    return _finish(job, path, {"video_type": "text_short"})


def _audio_video(job: GenerationJob, data: dict[str, Any]) -> dict[str, Any]:
    from engine.services.text_video_creator import create_sound_short

    audio = upload_dir(job.pk) / data["audio_file"]
    path = _output_path(data["output_name"])
    create_sound_short(
        text=data["text"],
        audio_path=str(audio),
        output_path=str(path),
        background_color=data.get("background_color"),
        text_color=data["text_color"],
        font_size=data["font_size"],
    )
    return _finish(job, path, {"video_type": "sound_short"})


def _sound_video(job: GenerationJob, data: dict[str, Any]) -> dict[str, Any]:
    from engine.services import narration
    from engine.services.text_video_creator import create_sound_short

    config = narration.current_config()
    if data.get("voice_id"):
        config.voice = str(data["voice_id"])
        config.voice_label = ""
        config.source = "request"
    report("step", agent="narration", status="running")
    speech = narration.synthesize(data["text"], upload_dir(job.pk) / "narration.mp3", config)
    report("step", agent="narration", status="done")
    check_cancelled()
    path = _output_path(data["output_name"])
    try:
        create_sound_short(
            text=data["text"],
            audio_path=str(speech.path),
            output_path=str(path),
            background_color=data.get("background_color"),
            text_color=data["text_color"],
            font_size=data["font_size"],
            word_timings=speech.words,
        )
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return _finish(job, path, {"video_type": "sound_short", **speech.metadata()})


def _lofi(job: GenerationJob, data: dict[str, Any]) -> dict[str, Any]:
    from engine.services.video_creator import create_video_from_images_and_audio

    folder = upload_dir(job.pk)
    output_dir = folder / "output"
    output_dir.mkdir(exist_ok=True)
    rendered = create_video_from_images_and_audio(
        image_paths=[str(folder / name) for name in data["image_files"]],
        audio_path=str(folder / data["audio_file"]),
        output_path=str(output_dir),
        output_name=data["output_name"],
        repeat_minutes=data["repeat_minutes"],
    )
    path = _output_path(data["output_name"])
    shutil.move(rendered, path)
    return _finish(job, path, {"video_type": "lofi", "repeat_minutes": data["repeat_minutes"]})


def _producer_short(job: GenerationJob, data: dict[str, Any]) -> dict[str, Any]:
    from engine.services.output_filename import resolve_output_name
    from engine.services.video_producer import (
        produce_sound_short_simple,
        produce_text_short_simple,
    )

    if data["mode"] == "sound":
        result = produce_sound_short_simple(
            text=data["text"],
            output_name=resolve_output_name(data["text"], default_stem="sound-short"),
        )
    else:
        result = produce_text_short_simple(
            text=data["text"],
            output_name=resolve_output_name(data["text"], default_stem="text-short"),
        )
    file_name = Path(str(result.get("output_path", ""))).name
    asset = register_asset(file_name, project=job.project, job=job)
    return {"report": result, "media": [asset_payload(asset)] if asset else []}


RENDERERS = {
    "text_video": _text_video,
    "audio_video": _audio_video,
    "sound_video": _sound_video,
    "lofi": _lofi,
    "producer_short": _producer_short,
}


@register("render")
def handle_render(job: GenerationJob) -> dict[str, Any]:
    tool = str(job.input.get("tool") or "")
    renderer = RENDERERS.get(tool)
    if renderer is None:
        raise ValueError(f"Unknown render tool '{tool}'.")
    report("step", agent="renderer", status="running")
    try:
        result = renderer(job, job.input)
    finally:
        shutil.rmtree(Path(settings.FRAMEFUSION_UPLOAD_DIR) / str(job.pk), ignore_errors=True)
    report("step", agent="renderer", status="done")
    return result
