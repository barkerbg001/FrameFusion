import struct
import wave
from pathlib import Path

import pytest
from app.main import app
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "fixtures"
    directory.mkdir()

    image_path = directory / "test.png"
    Image.new("RGB", (64, 64), color=(120, 80, 200)).save(image_path)

    audio_path = directory / "test.wav"
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
def test_image(fixtures_dir: Path) -> Path:
    return fixtures_dir / "test.png"


@pytest.fixture
def test_audio(fixtures_dir: Path) -> Path:
    return fixtures_dir / "test.wav"


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "output"
    directory.mkdir()
    return directory


def ffmpeg_available() -> bool:
    import shutil

    return shutil.which("ffmpeg") is not None


requires_ffmpeg = pytest.mark.skipif(
    not ffmpeg_available(),
    reason="FFmpeg is required for video encoding tests",
)
