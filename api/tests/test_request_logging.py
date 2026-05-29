import logging
from unittest.mock import patch

import pytest
from app.core.request_logging import CORRELATION_ID_HEADER
from fastapi.testclient import TestClient


def test_health_returns_correlation_id_header(client: TestClient):
    response = client.get("/health", headers={CORRELATION_ID_HEADER: "test-request-123"})

    assert response.status_code == 200
    assert response.headers[CORRELATION_ID_HEADER] == "test-request-123"


def test_health_generates_correlation_id_when_missing(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers[CORRELATION_ID_HEADER]
    assert len(response.headers[CORRELATION_ID_HEADER]) == 36


def test_request_logging_records_duration_and_output_size(
    client: TestClient,
    test_image,
    test_audio,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
):
    output_file = tmp_path / "result.mp4"
    output_file.write_bytes(b"0123456789")

    with caplog.at_level(logging.INFO, logger="app.request"):
        with patch(
            "app.routers.lofi.create_video_from_images_and_audio",
            return_value=str(output_file),
        ):
            response = client.post(
                "/api/lofi/generate-video",
                data={"repeat_minutes": "1"},
                files={
                    "images": ("test.png", test_image.read_bytes(), "image/png"),
                    "audio": ("test.wav", test_audio.read_bytes(), "audio/wav"),
                },
            )

    assert response.status_code == 200
    assert response.content == b"0123456789"

    completed_logs = [
        record
        for record in caplog.records
        if record.name == "app.request" and record.getMessage() == "request completed"
    ]
    assert completed_logs

    lofi_log = next(
        record
        for record in completed_logs
        if record.path == "/api/lofi/generate-video"
    )

    assert lofi_log.correlation_id
    assert lofi_log.duration_ms >= 0
    assert lofi_log.output_size_bytes == len(response.content)


def test_request_logging_records_json_response_size(client: TestClient, caplog):
    with caplog.at_level(logging.INFO, logger="app.request"):
        response = client.get("/health")

    assert response.status_code == 200

    health_log = next(
        record
        for record in caplog.records
        if record.name == "app.request"
        and record.getMessage() == "request completed"
        and record.path == "/health"
    )
    assert health_log.correlation_id == response.headers[CORRELATION_ID_HEADER]
    assert health_log.duration_ms >= 0
    assert health_log.output_size_bytes > 0
