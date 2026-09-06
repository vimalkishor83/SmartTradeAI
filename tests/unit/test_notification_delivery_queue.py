"""Regression coverage for the notification delivery queue contract."""

from app.models.notification import Notification


def test_notification_model_declares_delivery_queue_index():
    indexes = {index.name: tuple(column.name for column in index.columns)
               for index in Notification.__table__.indexes}

    assert indexes["idx_notif_delivery_queue"] == ("is_sent", "created_at", "id")


def test_notification_worker_uses_deterministic_pending_order():
    from pathlib import Path

    source = (Path(__file__).parents[2] / "app" / "tasks" / "notification_tasks.py").read_text(encoding="utf-8")

    assert ".order_by(Notification.created_at.asc(), Notification.id.asc())" in source
    assert ".limit(50).all()" in source
