"""Regression coverage for the notification delivery queue contract."""

from app.models.notification import Notification


def test_notification_model_declares_delivery_queue_index():
    indexes = {index.name: tuple(column.name for column in index.columns)
               for index in Notification.__table__.indexes}

    assert indexes["idx_notif_delivery_queue"] == ("is_sent", "created_at", "id")
    assert indexes["uq_notif_user_key"] == ("user_id", "notification_key")
    assert Notification.__table__.indexes  # keep the model-level constraint registered


def test_notification_worker_uses_deterministic_pending_order():
    from pathlib import Path

    source = (Path(__file__).parents[2] / "app" / "tasks" / "notification_tasks.py").read_text(encoding="utf-8")

    assert ".order_by(Notification.created_at.asc(), Notification.id.asc())" in source
    assert ".limit(50).all()" in source
    assert "Telegram delivery was not accepted" in source


def test_telegram_delivery_failure_releases_claim_for_retry(app):
    from unittest.mock import patch

    from app.extensions import db
    from app.models.user import User
    from app.tasks.notification_tasks import send_pending_notifications

    with app.app_context():
        user = User.query.filter_by(username="admin").first()
        user.telegram_enabled = True
        user.telegram_chat_id = "12345"
        notification = Notification(
            user_id=user.id,
            title="Terminal event",
            message="Target details",
            notification_type="terminal_signal_event",
            channel="telegram",
            notification_key="test-retry-event",
        )
        db.session.add(notification)
        db.session.commit()

        with patch("app.tasks.notification_tasks._send_telegram", return_value=False):
            send_pending_notifications(app)

        db.session.refresh(notification)
        assert notification.is_sent is False
        assert notification.sent_at is None
