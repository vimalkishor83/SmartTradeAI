"""Regression coverage for honest automatic signal confidence inputs."""

import pandas as pd

from app.services.signals.engine import SignalEngine


def _frame():
    index = pd.date_range("2026-01-01", periods=60, freq="h")
    close = pd.Series(range(100, 160), index=index, dtype=float)
    return pd.DataFrame(
        {
            "open": close - 0.25,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100.0,
        },
        index=index,
    )


def test_automatic_score_has_no_fabricated_ai_component():
    engine = SignalEngine()
    indicators = {
        "ema9": 159.0,
        "ema21": 158.0,
        "ema50": 155.0,
        "ema100": 150.0,
        "ema200": 140.0,
        "vwap": 150.0,
        "supertrend_direction": "up",
        "ichimoku_senkou_a": 145.0,
        "ichimoku_senkou_b": 146.0,
        "rsi": 65.0,
        "macd": 2.0,
        "macd_signal": 1.0,
        "macd_hist": 1.0,
    }

    direction, scores, _ = engine._score_signal(
        indicators, _frame(), "crypto", threshold=0.55, patterns=[], timeframe="1h",
    )

    assert direction == "BUY"
    assert scores["ai"] == 0


def test_manual_ai_boost_remains_a_separate_real_model_input():
    engine = SignalEngine()
    rule_scores = {"trend": 25, "momentum": 16, "volume": 6, "pattern": 12, "ai": 0}
    with_ai = dict(rule_scores, ai=10)

    rule_confidence = engine._compute_confidence(rule_scores, None, "BUY")
    ai_confidence = engine._compute_confidence(with_ai, None, "BUY")

    assert ai_confidence > rule_confidence
    assert rule_scores["ai"] == 0
