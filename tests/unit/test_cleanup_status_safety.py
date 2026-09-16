import json


def test_cleanup_status_is_read_only_and_sanitizes_snapshot(app, monkeypatch, tmp_path):
    from app.services import cleanup_status

    status_file = tmp_path / "status.json"
    status_file.write_text(json.dumps({
        "state": "completed",
        "mode": "apply",
        "completed_at": "2026-09-16T03:30:00Z",
        "candidate_count": 3,
        "skipped_count": 2,
        "bytes_processed": 4096,
        "secret": "must not escape",
    }), encoding="utf-8")
    monkeypatch.setattr(cleanup_status, "STATUS_FILE", status_file)

    with app.app_context():
        payload = cleanup_status.get_cleanup_status()

    assert payload["available"] is True
    assert payload["snapshot_available"] is True
    assert payload["snapshot"]["candidate_count"] == 3
    assert "secret" not in payload["snapshot"]
    assert payload["policy"]["arbitrary_paths_allowed"] is False
    assert payload["policy"]["frequency"] == "daily"


def test_cleanup_status_handles_missing_host_snapshot(app, monkeypatch, tmp_path):
    from app.services import cleanup_status

    monkeypatch.setattr(cleanup_status, "STATUS_FILE", tmp_path / "missing.json")

    with app.app_context():
        payload = cleanup_status.get_cleanup_status()

    assert payload["available"] is True
    assert payload["snapshot_available"] is False
    assert payload["snapshot"]["state"] == "not_run"


def test_cleanup_status_is_unavailable_in_production(app, monkeypatch):
    from app.services import cleanup_status

    monkeypatch.setenv("FLASK_ENV", "production")

    with app.app_context():
        payload = cleanup_status.get_cleanup_status()

    assert payload == {"available": False, "reason": "development-only"}


def test_cleanup_status_endpoint_requires_admin(client):
    response = client.get("/api/v1/admin/cleanup/status")

    assert response.status_code == 401
