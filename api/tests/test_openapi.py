from pathlib import Path

from scripts.export_openapi import export_openapi


def test_export_openapi_writes_expected_schemas(tmp_path: Path) -> None:
    output = tmp_path / "openapi.json"
    export_openapi(output)

    text = output.read_text(encoding="utf-8")
    assert "JobSummaryResponse" in text
    assert "JobCreateResponse" in text
    assert "HealthResponse" in text
    assert "/health" in text


def test_committed_openapi_is_up_to_date() -> None:
    api_root = Path(__file__).resolve().parents[1]
    committed = api_root / "openapi.json"
    assert committed.is_file(), "api/openapi.json is missing; run python scripts/export_openapi.py"

    fresh = export_openapi()
    assert committed.read_text(encoding="utf-8") == fresh.read_text(
        encoding="utf-8"
    ), "api/openapi.json is stale; run python scripts/export_openapi.py"
