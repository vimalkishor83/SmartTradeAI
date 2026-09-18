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


def test_personal_telegram_row_is_sent_when_individual_delivery_enabled(app):
    """channel="telegram" rows (e.g. terminal-live-read events queued by
    live_read_notifications.py) are real personal alerts under the
    news_group_individual_signals delivery mode -- they must actually be
    sent, not unconditionally skipped as a stale "group-only" era would
    have done. See notification_tasks.py's generic sweep."""
    from unittest.mock import patch

    from app.extensions import db
    from app.models.user import User
    from app.tasks.notification_tasks import send_pending_notifications

    with app.app_context():
        app.config["TELEGRAM_NOTIFICATIONS_ENABLED"] = True
        app.config["TELEGRAM_DELIVERY_MODE"] = "news_group_individual_signals"
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

        with patch("app.tasks.notification_tasks._send_telegram", return_value=True) as mock_send:
            send_pending_notifications(app)

        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs.get("category") == "watchlist"
        db.session.refresh(notification)
        assert notification.is_sent is True
        assert notification.delivery_status == "sent"


def test_personal_telegram_row_retries_on_send_failure(app):
    from unittest.mock import patch

    from app.extensions import db
    from app.models.user import User
    from app.tasks.notification_tasks import send_pending_notifications

    with app.app_context():
        app.config["TELEGRAM_NOTIFICATIONS_ENABLED"] = True
        app.config["TELEGRAM_DELIVERY_MODE"] = "news_group_individual_signals"
        user = User.query.filter_by(username="admin").first()
        user.telegram_enabled = True
        user.telegram_chat_id = "12345"
        notification = Notification(
            user_id=user.id,
            title="Retry test",
            message="Bounded",
            notification_type="test",
            channel="telegram",
            notification_key="bounded-retry-event",
        )
        db.session.add(notification)
        db.session.commit()

        with patch("app.tasks.notification_tasks._send_telegram", return_value=False):
            for _ in range(3):
                notification.next_attempt_at = None
                db.session.commit()
                send_pending_notifications(app)

        db.session.refresh(notification)
        assert notification.attempt_count == 3
        assert notification.delivery_status == "dead_letter"
