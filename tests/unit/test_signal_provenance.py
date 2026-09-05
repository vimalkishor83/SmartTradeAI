"""Unit coverage for live-signal provenance without invoking the market feed."""

from datetime import datetime, timezone

import pandas as pd

from app.services.signals.provenance import build_signal_provenance


def _frame():
    index = pd.date_range("2026-09-05 08:00", periods=3, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "volume": [10.0, 11.0, 12.0],
        },
        index=index,
    )


def test_signal_provenance_is_stable_and_captures_exact_frame():
    first = build_signal_provenance(_frame(), source="automatic")
    second = build_signal_provenance(_frame(), source="automatic")

    assert first == second
    assert first["generation_source"] == "automatic"
    assert first["engine_version"] == "signal-engine-v1"
    assert first["model_version"] == "not_applicable"
    assert len(first["data_fingerprint"]) == 64
    assert first["data_candles"] == 3
    assert first["data_start"] == datetime(2026, 9, 5, 8, 0, tzinfo=None)
    assert first["data_end"] == datetime(2026, 9, 5, 10, 0, tzinfo=None)


def test_signal_provenance_changes_when_model_or_candle_changes():
    frame = _frame()
    automatic = build_signal_provenance(frame, source="automatic")
    manual = build_signal_provenance(
        frame, source="manual", model_version="ensemble-calibrated-v1",
    )
    changed = frame.copy()
    changed.iloc[-1, changed.columns.get_loc("close")] = 104.0
    changed_data = build_signal_provenance(changed, source="automatic")

    assert manual["generation_source"] == "manual"
    assert manual["model_version"] == "ensemble-calibrated-v1"
    assert manual["data_fingerprint"] == automatic["data_fingerprint"]
    assert changed_data["data_fingerprint"] != automatic["data_fingerprint"]


def test_ai_predictor_fallback_does_not_claim_a_model_version():
    from app.services.ai.predictor import ai_predictor

    result = ai_predictor.predict(None, "TEST", "1h")
    assert result["model_version"] is None
