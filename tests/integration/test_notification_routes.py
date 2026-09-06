"""Integration coverage for user-scoped notification pagination."""

from datetime import datetime

import pytest


@pytest.fixture
def notification_headers(app):
    with app.app_context():
        from app.models.user import User
        from flask_jwt_extended import create_access_token

        user = User.query.filter_by(username="admin").first()
        token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}


def test_notifications_are_user_scoped_and_stably_ordered(app, client, notification_headers):
    with app.app_context():
        from app.extensions import db
        from app.models.notification import Notification
        from app.models.user import User

        owner = User.query.filter_by(username="admin").first()
        other = User(username="notification-other", email="notification-other@example.com", role_id=owner.role_id)
        other.set_password("TestPass123!")
        db.session.add(other)
        db.session.flush()
        timestamp = datetime(2026, 9, 6, 12, 0, 0)
        db.session.add_all([
            Notification(user_id=owner.id, title="Older", message="older", is_read=True, created_at=timestamp),
            Notification(user_id=owner.id, title="Newer ID", message="newer", is_read=False, created_at=timestamp),
            Notification(user_id=other.id, title="Private", message="private", is_read=False, created_at=timestamp),
        ])
        db.session.commit()

    response = client.get("/api/v1/notifications/?page=1", headers=notification_headers)

    assert response.status_code == 200
    payload = response.get_json()
    assert [item["title"] for item in payload["notifications"]] == ["Newer ID", "Older"]
    assert payload["unread_count"] == 1
    assert payload["total"] == 2


def test_notifications_unread_filter_preserves_unread_count(app, client, notification_headers):
    with app.app_context():
        from app.extensions import db
        from app.models.notification import Notification
        from app.models.user import User

        owner_id = User.query.filter_by(username="admin").first().id
        db.session.add(Notification(
            user_id=owner_id, title="Unread two", message="unread", is_read=False,
            created_at=datetime(2026, 9, 6, 13, 0, 0),
        ))
        db.session.commit()

    response = client.get("/api/v1/notifications/?unread=true", headers=notification_headers)

    assert response.status_code == 200
    payload = response.get_json()
    assert all(item["is_read"] is False for item in payload["notifications"])
    assert payload["unread_count"] == payload["total"]
