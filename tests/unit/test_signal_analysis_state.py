"""Regression coverage for explicit position-analysis states."""

import pandas as pd

from app.services.signals import engine as engine_module
from app.services.signals.engine import SignalEngine


class _Asset:
    market = "crypto"
    symbol = "ANALYSISSTATE"


def _frame():
    close = pd.Series([100.0] * 60)
    return pd.DataFrame({"close": close})


def _stub_common(monkeypatch, engine, direction, confidence, reasons=None):
    monkeypatch.setattr(engine, "_session_gate", lambda _market: True)
    monkeypatch.setattr(engine_module, "calculate_all_indicators", lambda _df: {"atr": 1.0})
    monkeypatch.setattr(engine, "_volatility_gate", lambda _atr_pct: (True, "normal"))
    monkeypatch.setattr(engine, "_mtf_gate", lambda _df: None)
    monkeypatch.setattr(engine, "_mtf_supertrend_confirmation", lambda _asset, _tf: [])
    monkeypatch.setattr(engine_module, "detect_patterns", lambda _df: [])
    monkeypatch.setattr(
        engine,
        "_score_signal",
        lambda *args, **kwargs: (direction, {"trend": 20, "momentum": 12, "volume": 5, "pattern": 8, "ai": 0}, reasons or []),
    )
    monkeypatch.setattr(engine, "_compute_confidence", lambda *args, **kwargs: confidence)
    monkeypatch.setattr(engine, "_smc_gate_enabled", lambda: False)
    monkeypatch.setattr(engine, "_smc_liquidity_enabled", lambda: False)
    monkeypatch.setattr(engine, "_smc_sr_enabled", lambda: False)


def test_hold_analysis_is_explicitly_no_signal(monkeypatch):
    engine = SignalEngine()
    _stub_common(monkeypatch, engine, "HOLD", 0.0)

    result = engine.analyze(_frame(), _Asset(), "1h")

    assert result["available"] is True
    assert result["analysis_state"] == "NO_SIGNAL"
    assert result["qualifies_as_signal"] is False
    assert result["no_signal_reason"] == "no_clear_direction"
    assert "No clear directional consensus" in result["no_signal_message"]


def test_directional_read_below_threshold_is_not_presented_as_signal(monkeypatch):
    engine = SignalEngine()
    _stub_common(monkeypatch, engine, "BUY", 64.5)
    monkeypatch.setattr(engine, "_structure_stop", lambda *args: 98.0)
    monkeypatch.setattr(engine, "_calculate_targets", lambda *args: (102.0, 104.0, 106.0))
    monkeypatch.setattr(engine, "_nearest_structure_level", lambda *args: None)
    monkeypatch.setattr(engine, "_invalidation_conditions", lambda *args: [])
    monkeypatch.setattr(engine, "_target_allocations", lambda *args: [])
    monkeypatch.setattr(engine, "_risk_reward", lambda *args: 1.0)

    result = engine.analyze(_frame(), _Asset(), "1h")

    assert result["analysis_state"] == "NO_SIGNAL"
    assert result["signal_type"] == "BUY"
    assert result["qualifies_as_signal"] is False
    assert result["no_signal_reason"] == "below_confidence_threshold"
    assert "64.5%" in result["no_signal_message"]


def test_missing_analysis_data_is_unavailable_not_no_signal():
    result = SignalEngine().analyze(None, _Asset(), "1h")

    assert result == {
        "available": False,
        "analysis_state": "UNAVAILABLE",
        "reason": "insufficient_data",
    }
