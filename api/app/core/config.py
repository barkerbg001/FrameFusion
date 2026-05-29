import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# api/ directory (parent of app/)
API_ROOT = Path(__file__).resolve().parents[2]

UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", API_ROOT / "uploads"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", API_ROOT / "output"))


def ensure_directories() -> None:
    """Create runtime data directories if they do not exist."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
