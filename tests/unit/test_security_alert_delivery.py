"""Regression coverage for send_security_alert: it used to call
send_group_message(text) with no category, which that function silently
rejects (it only allows category="news"), meaning every security event
(new IP login, failed login, anonymous visit, new visitor) was a dead
no-op even when a security chat id was configured. It must now deliver
directly to PlatformConfig.telegram_security_chat_id."""
from unittest.mock import patch, MagicMock

from app.tasks.notification_tasks import send_security_alert


def test_security_alert_skips_silently_with_no_chat_id_configured(app):
    with app.app_context():
        with patch("app.services.platform_config.get_platform_config", return_value={}):
            assert send_security_alert("test") is False


def test_security_alert_posts_directly_to_security_chat_id(app):
    with app.app_context():
        app.config["TELEGRAM_BOT_TOKEN"] = "test-token"
        mock_response = MagicMock(ok=True)
        with patch("app.services.platform_config.get_platform_config",
                   return_value={"telegram_security_chat_id": "-100999"}), \
             patch("requests.post", return_value=mock_response) as mock_post:
            result = send_security_alert("🔐 test alert")

        assert result is True
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["chat_id"] == "-100999"
        assert kwargs["json"]["text"] == "🔐 test alert"
