"""Regression coverage for legacy provider log timestamps."""

from datetime import datetime, timezone

from app.models.api_config import APILog


def test_api_log_to_dict_tolerates_null_created_at():
    log = APILog(action="fetch", status="error", created_at=None)

    assert log.to_dict()["created_at"] is None


def test_api_log_to_dict_serializes_created_at_as_isoformat():
    created_at = datetime(2026, 9, 6, 10, 30, tzinfo=timezone.utc)
    log = APILog(action="fetch", status="ok", created_at=created_at)

    assert log.to_dict()["created_at"] == created_at.isoformat()
