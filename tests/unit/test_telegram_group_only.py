from types import SimpleNamespace
from unittest.mock import Mock

from app.services.safety import (
    telegram_delivery_mode,
    telegram_group_delivery_enabled,
    telegram_individual_delivery_enabled,
)


def test_development_telegram_delivery_is_group_only(app):
    with app.app_context():
        app.config["TELEGRAM_NOTIFICATIONS_ENABLED"] = True
        app.config["TELEGRAM_DELIVERY_MODE"] = "group_only"

        assert telegram_delivery_mode() == "group_only"
        assert telegram_group_delivery_enabled() is True
        assert telegram_individual_delivery_enabled() is False


def test_individual_sender_never_calls_telegram(app, monkeypatch):
    with app.app_context():
        app.config["TELEGRAM_NOTIFICATIONS_ENABLED"] = True
        app.config["TELEGRAM_DELIVERY_MODE"] = "group_only"
        requests_post = Mock()
        monkeypatch.setattr("requests.post", requests_post)

        from app.tasks.notification_tasks import _send_telegram

        user = SimpleNamespace(
            id=1,
            username="user",
            telegram_chat_id="123",
            get_telegram_bot_token=lambda: "user-token",
        )
        assert _send_telegram(user, "must not be sent") is False
        requests_post.assert_not_called()


def test_group_sender_blocks_non_primary_chat_and_accepts_primary(app, monkeypatch):
    with app.app_context():
        app.config["TELEGRAM_NOTIFICATIONS_ENABLED"] = True
        app.config["TELEGRAM_DELIVERY_MODE"] = "group_only"
        channel = SimpleNamespace(
            group_chat_id="-100-primary",
            matches=lambda market, category, timeframe: True,
        )
        monkeypatch.setattr(
            "app.services.telegram_delivery.primary_group_channel",
            lambda: channel,
        )
        response = SimpleNamespace(ok=True, status_code=200)
        requests_post = Mock(return_value=response)
        monkeypatch.setattr("requests.post", requests_post)

        from app.services.telegram_delivery import send_group_message

        assert send_group_message("blocked", chat_id="-100-other") is False
        requests_post.assert_not_called()

        assert send_group_message("allowed", chat_id="-100-primary") is True
        requests_post.assert_called_once()
