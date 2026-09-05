import json
import re
from unittest.mock import patch

from app import _safe_request_id


def test_valid_request_id_is_returned_unchanged(client):
    response = client.get(
        "/api/v1/system/health",
        headers={"X-Request-ID": "edge-req_2026.09:abc"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "alive"
    assert response.headers["X-Request-ID"] == "edge-req_2026.09:abc"


def test_missing_request_id_is_generated(client):
    response = client.get("/api/v1/system/health")

    assert response.status_code == 200
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


def test_unsafe_request_id_is_replaced(client):
    response = client.get(
        "/api/v1/system/health",
        headers={"X-Request-ID": "bad request-id"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "bad request-id"
    assert re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", response.headers["X-Request-ID"])
    assert _safe_request_id("bad\nrequest-id") != "bad\nrequest-id"


def test_request_completion_log_contains_safe_timing_fields(app, client):
    with patch.object(app.logger, "info") as log_info:
        response = client.get(
            "/api/v1/system/health?secret=must-not-be-logged",
            headers={"X-Request-ID": "timed-request"},
        )

    assert response.status_code == 200
    log_call = next(
        call for call in log_info.call_args_list
        if call.args and call.args[0] == "request_complete %s"
    )
    payload = json.loads(log_call.args[1])
    assert payload == {
        "duration_ms": payload["duration_ms"],
        "endpoint": "system.health",
        "method": "GET",
        "path": "/api/v1/system/health",
        "request_id": "timed-request",
        "status": 200,
    }
    assert "secret" not in log_call.args[1]


def test_static_assets_keep_correlation_header_without_log_noise(app, client):
    with patch.object(app.logger, "info") as log_info:
        response = client.get("/static/css/main.css")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert not any(
        call.args and call.args[0] == "request_complete %s"
        for call in log_info.call_args_list
    )
