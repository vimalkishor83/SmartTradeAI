"""Regression coverage for persisted Terminal live-read context."""

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
        assert row.to_dict()["data_quality"]["candle_count"] == 100
