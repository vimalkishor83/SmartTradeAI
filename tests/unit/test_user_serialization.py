"""Regression coverage for legacy account timestamps."""

from datetime import datetime, timezone

from app.models.user import User


def test_user_to_dict_tolerates_null_created_at():
    user = User(username="legacy-user", email="legacy@example.com", created_at=None)

    assert user.to_dict()["created_at"] is None


def test_user_to_dict_serializes_created_at_as_isoformat():
    created_at = datetime(2026, 9, 6, 10, 30, tzinfo=timezone.utc)
    user = User(username="current-user", email="current@example.com", created_at=created_at)

    assert user.to_dict()["created_at"] == created_at.isoformat()
