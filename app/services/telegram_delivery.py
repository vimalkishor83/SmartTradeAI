"""Central Telegram delivery boundary.

The shared Telegram group is reserved for market-news updates. Signal and
other personal alerts must use the individual delivery path instead.
"""

import logging

from flask import current_app

logger = logging.getLogger(__name__)


def primary_group_channel():
    from app.models.telegram_alert_channel import TelegramAlertChannel

    return (
        TelegramAlertChannel.query
        .filter_by(is_active=True)
        .order_by(TelegramAlertChannel.id.asc())
        .first()
    )


def send_group_message(text: str, *, chat_id: str | None = None,
                       market: str | None = None,
                       category: str | None = None,
                       timeframe: str | None = None) -> bool:
    """Send only to the configured primary group, or safely skip."""
    from app.services.safety import telegram_group_delivery_enabled

    if category != "news":
        logger.info("Telegram group delivery skipped because the group is news-only")
        return False
    if not telegram_group_delivery_enabled():
        logger.info("Telegram group delivery blocked by environment safety gate")
        return False

    try:
        channel = primary_group_channel()
    except Exception as exc:
        logger.error("Telegram group configuration lookup failed: %s", type(exc).__name__)
        return False
    if not channel:
        logger.info("Telegram group delivery skipped because no active group is configured")
        return False
    if chat_id is not None and str(chat_id) != str(channel.group_chat_id):
        logger.warning("Telegram delivery to a non-primary chat was blocked")
        return False
    if market and channel.markets and market not in channel.markets:
        return False

    token = current_app.config.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.info("Telegram group delivery skipped because the platform bot is not configured")
        return False

    try:
        import requests

        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": channel.group_chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=5,
        )
        if not response.ok:
            logger.warning("Telegram group delivery rejected with HTTP %s", response.status_code)
            return False
        return True
    except Exception as exc:
        logger.error("Telegram group delivery failed: %s", type(exc).__name__)
        return False
