"""Regression coverage for user-level Terminal Telegram lifecycle alerts."""

from app.extensions import db
from app.models.asset import Asset
from app.models.live_read_log import LiveReadLog
from app.models.notification import Notification
from app.models.platform_config import PlatformConfig
from app.models.user import User


def _live_row(asset):
    return LiveReadLog(
        asset_id=asset.id,
        timeframe="15m",
        signal_type="BUY",
        confidence_score=78,
        entry_price=100,
        stop_loss=95,
        target1=105,
        target2=110,
        target3=115,
        snapshot={"risk_reward": 2.0},
        reasoning="Trend aligns",
        event_history=[{"type": "generated", "price": 100}],
    )


def test_live_read_event_queue_is_user_scoped_and_idempotent(app):
    from app.services.platform_config import invalidate_platform_config
    from app.services.signals.live_read_notifications import (
        enqueue_live_read_event_notifications,
    )

    with app.app_context():
        owner = User.query.filter_by(username="admin").first()
        owner.telegram_enabled = True
        owner.telegram_chat_id = "12345"
        owner.set_telegram_bot_token("test-token")
        asset = Asset(
            symbol="ALERTTEST", name="Alert Test", market="crypto", is_active=True,
        )
        db.session.add(asset)
        db.session.flush()
        config = PlatformConfig.get_singleton()
        config.telegram_signal_individual_markets = ["crypto"]
        invalidate_platform_config()

        row = _live_row(asset)
        db.session.add(row)
        db.session.flush()
        current = row.event_history + [
            {"type": "target1", "price": 105},
            {"type": "trailing_stop", "stage": 1, "price": 101},
        ]

        queued = enqueue_live_read_event_notifications(row, current, row.event_history)
        db.session.commit()
        assert queued == 2
        assert Notification.query.filter_by(
            user_id=owner.id, notification_type="terminal_signal_event",
        ).count() == 2

        queued_again = enqueue_live_read_event_notifications(row, current, row.event_history)
        db.session.commit()
        assert queued_again == 0
        assert Notification.query.filter_by(
            user_id=owner.id, notification_type="terminal_signal_event",
        ).count() == 2

        notifications = Notification.query.filter_by(user_id=owner.id).all()
        assert any("TARGET 1 HIT" in item.title for item in notifications)
        assert any("TRAILING STOP ACTIVATED" in item.title for item in notifications)
        assert all("TARGET 1 HIT" not in item.message for item in notifications)


def test_live_read_telegram_footer_has_disclaimer_link_and_context_gap(app):
    from app.services.signals.live_read_notifications import format_live_read_event

    with app.app_context():
        asset = Asset(
            symbol="FOOTERTEST", name="Footer Test", market="crypto", is_active=True,
        )
        db.session.add(asset)
        db.session.flush()
        row = _live_row(asset)

        text = format_live_read_event(row, {"type": "target1", "price": 105})

        assert "\n\n⚠️ _Disclaimer:" in text
        assert "[Read full disclaimer](https://smarttradeai.online/disclaimer)" in text


def test_live_read_worker_advances_existing_setup_without_terminal_request(app):
    from unittest.mock import patch

    from app.tasks.data_tasks import track_live_read_events

    with app.app_context():
        asset = Asset(
            symbol="WORKERTEST", name="Worker Test", market="crypto", is_active=True,
        )
        db.session.add(asset)
        db.session.flush()
        row = _live_row(asset)
        db.session.add(row)
        db.session.commit()

        with patch("app.services.data.fetcher.market_fetcher.fetch_ticker", return_value={"price": 106}):
            track_live_read_events(app)

        refreshed = db.session.get(LiveReadLog, row.id)
        assert refreshed.trail_stage == 1
        assert refreshed.trailing_stop == 101
        assert [event["type"] for event in refreshed.event_history] == [
            "generated", "target1", "trailing_stop",
        ]
