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


def test_signal_serializes_reproducibility_snapshot(app):
    with app.app_context():
        signal = Signal(
            signal_type="SELL",
            timeframe="15m",
            asset_id=1,
            generated_at=datetime.now(timezone.utc),
            generation_source="automatic",
            engine_version="signal-engine-v1",
            model_version="not_applicable",
            data_fingerprint="a" * 64,
            data_candles=220,
            data_start=datetime(2026, 9, 5, 8, 0),
            data_end=datetime(2026, 9, 5, 12, 45),
        )
        payload = signal.to_dict()
        provenance = payload["reproducibility"]
        assert provenance["generation_source"] == "automatic"
        assert provenance["engine_version"] == "signal-engine-v1"
        assert provenance["model_version"] == "not_applicable"
        assert len(provenance["data_fingerprint"]) == 64
        assert provenance["data_candles"] == 220
        assert provenance["data_start"] == "2026-09-05T08:00:00"
        assert provenance["data_end"] == "2026-09-05T12:45:00"
