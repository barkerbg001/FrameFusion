import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# api/ directory (parent of app/)
API_ROOT = Path(__file__).resolve().parents[2]

UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", API_ROOT / "uploads"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", API_ROOT / "output"))
JOBS_DIR = Path(os.getenv("JOBS_DIR", API_ROOT / "jobs"))
JOBS_DB_PATH = Path(os.getenv("JOBS_DB_PATH", API_ROOT / "jobs.db"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
JOB_QUEUE_BACKEND = os.getenv("JOB_QUEUE_BACKEND", "inline")

_cors_raw = os.getenv("CORS_ORIGINS", "*")
CORS_ORIGINS = [
    origin.strip() for origin in _cors_raw.split(",") if origin.strip()
] or ["*"]


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


MAX_IMAGE_COUNT = _int_env("MAX_IMAGE_COUNT", 10)
MAX_IMAGE_SIZE_BYTES = _int_env("MAX_IMAGE_SIZE_BYTES", 20 * 1024 * 1024)
MAX_AUDIO_SIZE_BYTES = _int_env("MAX_AUDIO_SIZE_BYTES", 100 * 1024 * 1024)


def ensure_directories() -> None:
    """Create runtime data directories if they do not exist."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
