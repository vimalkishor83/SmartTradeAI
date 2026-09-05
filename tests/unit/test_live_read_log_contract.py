"""Regression coverage for persisted Terminal live-read context."""

from datetime import datetime, timedelta
from unittest.mock import patch

from app.extensions import db
from app.models.asset import Asset
from app.models.live_read_log import LiveReadLog


def test_open_live_read_log_persists_data_quality_snapshot(app):
    from app.api.v1.signals import _open_live_read_log

    with app.app_context():
        asset = Asset(
            symbol="LIVEQUALITY",
            name="Live Quality Asset",
            market="crypto",
            is_active=True,
        )
        db.session.add(asset)
        db.session.flush()

        result = {
            "signal_type": "BUY",
            "confidence_score": 76.0,
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "target1": 105.0,
            "target2": 110.0,
            "target3": 115.0,
            "reasoning": "Trend and momentum align.",
            "reasoning_detail": [{"text": "Trend", "aligned": True}],
            "regime": "uptrend_normal",
            "data_quality": {
                "status": "GREEN",
                "provider": "delta_exchange",
                "candle_count": 100,
            },
        }

        with patch(
            "app.services.ai.llm_reasoning.generate_reasoning",
            return_value=None,
        ):
            log_id = _open_live_read_log(asset, "1h", result)

        assert log_id is not None
        row = db.session.get(LiveReadLog, log_id)
        assert row is not None
        assert row.data_quality["status"] == "GREEN"
        assert row.expires_at > row.generated_at
        assert row.to_dict()["data_quality"]["candle_count"] == 100


def test_expire_live_read_logs_records_neutral_outcome(app):
    from app.tasks.data_tasks import expire_live_read_logs

    with app.app_context():
        asset = Asset(
            symbol="LIVEEXPIRY",
            name="Live Expiry Asset",
            market="crypto",
            is_active=True,
        )
        db.session.add(asset)
        db.session.flush()
        stale = LiveReadLog(
            asset_id=asset.id,
            timeframe="1h",
            signal_type="BUY",
            entry_price=100.0,
            generated_at=datetime.utcnow() - timedelta(hours=5),
            expires_at=datetime.utcnow() - timedelta(minutes=1),
        )
        current = LiveReadLog(
            asset_id=asset.id,
            timeframe="1h",
            signal_type="SELL",
            entry_price=100.0,
            generated_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        db.session.add_all([stale, current])
        db.session.commit()

        expire_live_read_logs(app)

        assert db.session.get(LiveReadLog, stale.id).outcome == "expired"
        assert db.session.get(LiveReadLog, stale.id).resolved_at is not None
        assert db.session.get(LiveReadLog, current.id).outcome is None
