import os
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent

GENERATED_DIR = Path(os.getenv("FRAMEFUSION_OUTPUT_DIR") or API_ROOT / "generated").resolve()
PEXELS_CACHE_DIR = GENERATED_DIR / "pexels_cache"


def is_within(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    root = root.resolve()
    return resolved == root or root in resolved.parents
