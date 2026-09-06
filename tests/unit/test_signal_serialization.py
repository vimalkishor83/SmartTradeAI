"""Regression coverage for legacy signal timestamps."""

from datetime import datetime, timezone

from app.models.signal import Signal


def test_signal_to_dict_tolerates_null_generated_at(app):
    with app.app_context():
        signal = Signal(signal_type="BUY", timeframe="1h", asset_id=1, generated_at=None)

        assert signal.to_dict()["generated_at"] is None


def test_signal_to_dict_serializes_generated_at_as_isoformat(app):
    created_at = datetime(2026, 9, 6, 10, 30, tzinfo=timezone.utc)
    with app.app_context():
        signal = Signal(
            signal_type="SELL",
            timeframe="15m",
            asset_id=1,
            generated_at=created_at,
        )

        assert signal.to_dict()["generated_at"] == created_at.isoformat()
