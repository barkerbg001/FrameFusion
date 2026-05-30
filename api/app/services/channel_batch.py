from __future__ import annotations

from pathlib import Path

from app.jobs.progress import (
    reset_encode_progress_range,
    set_encode_progress_range,
    update_render_progress,
)
from app.services.shorts import create_shorts
from app.services.slideshow import create_slideshow

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def list_image_files(folder: Path) -> list[str]:
    files = [
        str(path)
        for path in sorted(folder.iterdir())
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    if not files:
        raise FileNotFoundError(f"No images found in folder: {folder}")
    return files


def iter_channel_folders(channel_root: Path) -> list[Path]:
    if not channel_root.exists():
        raise FileNotFoundError(f"Channel folder not found: {channel_root}")

    folders = sorted(path for path in channel_root.iterdir() if path.is_dir())
    if not folders:
        raise FileNotFoundError(f"No subfolders found in channel folder: {channel_root}")
    return folders


def render_channel_batch(
    channel_root: str,
    output_root: str,
    render_type: str,
    *,
    audio_path: str | None = None,
    orientation: str = "landscape",
    fps: int = 30,
    seconds_per_image: float = 1.0,
    max_duration_seconds: float | None = None,
) -> list[str]:
    channel_path = Path(channel_root)
    output_path = Path(output_root)
    output_path.mkdir(parents=True, exist_ok=True)

    if render_type not in {"slideshow", "shorts"}:
        raise ValueError("render_type must be 'slideshow' or 'shorts'")

    if render_type == "slideshow" and not audio_path:
        raise ValueError("audio_path is required for slideshow batch renders")

    rendered_files: list[str] = []
    folders = iter_channel_folders(channel_path)
    folder_count = len(folders)

    for index, folder in enumerate(folders):
        encode_start = 5 + (85 * index / folder_count)
        encode_end = 5 + (85 * (index + 1) / folder_count)
        range_token = set_encode_progress_range(encode_start, encode_end)
        update_render_progress(encode_start)

        image_paths = list_image_files(folder)
        output_name = f"{folder.name}.mp4"

        try:
            if render_type == "slideshow":
                output_file = create_slideshow(
                    image_paths=image_paths,
                    audio_path=audio_path,  # type: ignore[arg-type]
                    output_path=str(output_path),
                    output_name=output_name,
                    fps=fps,
                    orientation=orientation,
                )
            else:
                output_file = create_shorts(
                    image_paths=image_paths,
                    output_path=str(output_path),
                    output_name=output_name,
                    audio_path=audio_path,
                    seconds_per_image=seconds_per_image,
                    orientation=orientation,
                    max_duration_seconds=max_duration_seconds,
                    fps=fps,
                )
        finally:
            reset_encode_progress_range(range_token)

        rendered_files.append(output_file)

    return rendered_files
