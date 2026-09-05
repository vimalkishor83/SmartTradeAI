"""Regression coverage for persisted signal data-quality context."""

from datetime import datetime, timezone

from app.models.signal import Signal


def test_signal_serializes_data_quality_snapshot(app):
    with app.app_context():
        signal = Signal(
            signal_type="BUY",
            timeframe="1h",
            asset_id=1,
            generated_at=datetime.now(timezone.utc),
            data_quality={
                "status": "GREEN",
                "provider": "delta_exchange",
                "candle_count": 60,
                "last_candle_at": "2026-09-05T10:00:00+00:00",
            },
        )
        payload = signal.to_dict()
        assert payload["data_quality"]["status"] == "GREEN"
        assert payload["data_quality"]["candle_count"] == 60
