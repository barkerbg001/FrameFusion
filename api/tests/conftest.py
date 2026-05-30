import time
from pathlib import Path

import pytest
from app.core import config
from app.jobs import store
from app.main import app
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture(autouse=True)
def isolated_job_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    jobs_dir = tmp_path / "jobs"
    jobs_db = tmp_path / "jobs.db"
    monkeypatch.setattr(config, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(config, "JOBS_DB_PATH", jobs_db)
    monkeypatch.setattr(config, "JOB_QUEUE_BACKEND", "inline")
    store.init_db()


@pytest.fixture(autouse=True)
def disable_rate_limits_by_default(request: pytest.FixtureRequest):
    limiter = app.state.limiter
    previous = limiter.enabled
    if request.node.get_closest_marker("rate_limit") is None:
        limiter.enabled = False
    yield
    limiter.enabled = previous
    limiter.reset()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def fixtures_dir(tmp_path):
    directory = tmp_path / "fixtures"
    directory.mkdir()

    image_path = directory / "test.png"
    Image.new("RGB", (64, 64), color=(120, 80, 200)).save(image_path)

    audio_path = directory / "test.wav"
    import struct
    import wave

    sample_rate = 44_100
    duration_seconds = 0.5
    frame_count = int(sample_rate * duration_seconds)
    silent_frame = struct.pack("<h", 0)

    with wave.open(str(audio_path), "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(silent_frame * frame_count)

    return directory


@pytest.fixture
def test_image(fixtures_dir):
    return fixtures_dir / "test.png"


@pytest.fixture
def test_audio(fixtures_dir):
    return fixtures_dir / "test.wav"


@pytest.fixture
def output_dir(tmp_path):
    directory = tmp_path / "output"
    directory.mkdir()
    return directory


def wait_for_job(client: TestClient, job_id: str, *, timeout_seconds: float = 5.0) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] == "completed":
            return payload
        if payload["status"] == "failed":
            pytest.fail(f"Job failed: {payload}")
        time.sleep(0.05)
    pytest.fail(f"Job {job_id} did not complete within {timeout_seconds}s")


def ffmpeg_available() -> bool:
    import shutil

    return shutil.which("ffmpeg") is not None


requires_ffmpeg = pytest.mark.skipif(
    not ffmpeg_available(),
    reason="FFmpeg is required for video encoding tests",
)
