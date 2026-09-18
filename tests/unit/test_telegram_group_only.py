"""Focused tests for the Telegram routing policy."""

from types import SimpleNamespace
from unittest.mock import Mock

from app.services.safety import (
    telegram_delivery_mode,
    telegram_group_delivery_enabled,
    telegram_individual_delivery_enabled,
)


def test_news_group_and_individual_signal_policy_is_explicit(app):
    with app.app_context():
        app.config["TELEGRAM_NOTIFICATIONS_ENABLED"] = True
        app.config["TELEGRAM_DELIVERY_MODE"] = "news_group_individual_signals"

        assert telegram_delivery_mode() == "news_group_individual_signals"
        assert telegram_group_delivery_enabled() is True
        assert telegram_individual_delivery_enabled() is True


def test_individual_sender_is_blocked_when_environment_disables_telegram(app, monkeypatch):
    with app.app_context():
        app.config["TELEGRAM_NOTIFICATIONS_ENABLED"] = False
        app.config["TELEGRAM_DELIVERY_MODE"] = "news_group_individual_signals"
        requests_post = Mock()
        monkeypatch.setattr("requests.post", requests_post)

        from app.tasks.notification_tasks import _send_telegram

        user = SimpleNamespace(
            id=1,
            username="user",
            telegram_enabled=True,
            telegram_chat_id="123",
            get_telegram_bot_token=lambda: "user-token",
        )
        assert _send_telegram(user, "must not be sent") is False
        requests_post.assert_not_called()


def test_individual_sender_uses_user_chat_when_enabled(app, monkeypatch):
    with app.app_context():
        app.config["TELEGRAM_NOTIFICATIONS_ENABLED"] = True
        app.config["TELEGRAM_DELIVERY_MODE"] = "news_group_individual_signals"
        app.config["TELEGRAM_BOT_TOKEN"] = "platform-token"
        response = SimpleNamespace(ok=True, status_code=200)
        requests_post = Mock(return_value=response)
        monkeypatch.setattr("requests.post", requests_post)

        from app.tasks.notification_tasks import _send_telegram

        user = SimpleNamespace(
            id=1,
            username="user",
            telegram_enabled=True,
            telegram_chat_id="123",
            get_telegram_bot_token=lambda: None,
        )
        assert _send_telegram(user, "personal signal") is True
        requests_post.assert_called_once()
        assert requests_post.call_args.kwargs["json"]["chat_id"] == "123"


def test_group_sender_accepts_news_but_rejects_signal(app, monkeypatch):
    with app.app_context():
        app.config["TELEGRAM_NOTIFICATIONS_ENABLED"] = True
        app.config["TELEGRAM_DELIVERY_MODE"] = "news_group_individual_signals"
        app.config["TELEGRAM_BOT_TOKEN"] = "test-platform-token"
        channel = SimpleNamespace(
            group_chat_id="-100-primary",
            markets=[],
            is_active=True,
        )
        monkeypatch.setattr(
            "app.services.telegram_delivery.primary_group_channel",
            lambda: channel,
        )
        response = SimpleNamespace(ok=True, status_code=200)
        requests_post = Mock(return_value=response)
        monkeypatch.setattr("requests.post", requests_post)

        from app.services.telegram_delivery import send_group_message

        assert send_group_message("signal", chat_id="-100-primary", category="signal") is False
        requests_post.assert_not_called()

        assert send_group_message("news", chat_id="-100-primary", category="news") is True
        requests_post.assert_called_once()
