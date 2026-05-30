from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from app.jobs.progress import update_render_progress


def render_lofi_e2e(payload: dict[str, Any]) -> str:
    """Fast stub render for Playwright E2E (no FFmpeg)."""
    output_dir = Path(str(payload["output_dir"]))
    output_name = str(payload["output_name"])
    output_file = output_dir / output_name
    output_file.parent.mkdir(parents=True, exist_ok=True)

    update_render_progress(20)
    time.sleep(0.25)
    update_render_progress(60)
    time.sleep(0.25)
    update_render_progress(90)

    output_file.write_bytes(b"framefusion-e2e-video")
    return str(output_file)
