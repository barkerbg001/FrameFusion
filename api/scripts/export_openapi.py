"""Export the FastAPI OpenAPI schema to api/openapi.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.main import app  # noqa: E402


def export_openapi(output_path: Path | None = None) -> Path:
    destination = output_path or API_ROOT / "openapi.json"
    destination.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


if __name__ == "__main__":
    path = export_openapi()
    print(f"Wrote {path}")
