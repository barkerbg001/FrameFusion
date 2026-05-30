import pytest
from app.core import config
from app.jobs.models import JobType
from app.services.e2e_render import render_lofi_e2e


def test_render_lofi_e2e_writes_output(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "E2E_FAST_RENDER", True)

    output_dir = tmp_path / "output"
    output_path = render_lofi_e2e(
        {
            "output_dir": str(output_dir),
            "output_name": "e2e.mp4",
        }
    )

    assert output_path == str(output_dir / "e2e.mp4")
    assert (output_dir / "e2e.mp4").read_bytes() == b"framefusion-e2e-video"


def test_execute_job_uses_e2e_render_for_lofi(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "E2E_FAST_RENDER", True)

    from app.jobs.tasks import _execute_job

    output_dir = tmp_path / "output"
    result = _execute_job(
        JobType.LOFI,
        {
            "image_paths": [],
            "audio_path": "unused",
            "output_dir": str(output_dir),
            "output_name": "e2e.mp4",
            "repeat_minutes": 1,
        },
    )

    assert result.endswith("e2e.mp4")
