"""Regression coverage for notification payloads from legacy rows."""

from datetime import datetime, timezone

from app.models.notification import Notification


def test_notification_to_dict_preserves_null_created_at_without_500():
    notification = Notification(
        title="Signal",
        message="A signal is ready",
        created_at=None,
    )

    payload = notification.to_dict()

    assert payload["title"] == "Signal"
    assert payload["created_at"] is None


def test_notification_to_dict_serializes_created_at_as_isoformat():
    created_at = datetime(2026, 9, 6, 10, 30, tzinfo=timezone.utc)
    notification = Notification(
        title="Signal",
        message="A signal is ready",
        created_at=created_at,
    )

    assert notification.to_dict()["created_at"] == created_at.isoformat()
