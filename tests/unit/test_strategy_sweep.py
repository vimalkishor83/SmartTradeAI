import numpy as np
import pandas as pd

from app.services.backtesting.sweep import (
    SWEEP_STRATEGIES,
    SWEEP_TIMEFRAMES,
    _json_safe,
    resample_ohlcv,
)


def test_sweep_catalog_is_explicit_and_covers_requested_timeframes():
    assert [item["key"] for item in SWEEP_STRATEGIES] == [
        "rsi", "macd", "ema_crossover", "multi_factor",
    ]
    assert SWEEP_TIMEFRAMES == ("5m", "15m", "30m", "1h", "2h", "3h", "1d")


def test_three_hour_resampling_uses_ohlcv_aggregation():
    index = pd.date_range("2026-01-01", periods=6, freq="h")
    frame = pd.DataFrame({
        "open": [1, 2, 3, 4, 5, 6],
        "high": [2, 3, 4, 5, 6, 7],
        "low": [0, 1, 2, 3, 4, 5],
        "close": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5],
        "volume": [1, 2, 3, 4, 5, 6],
    }, index=index)
    result = resample_ohlcv(frame, "3h")
    assert len(result) == 3
    assert result.iloc[0]["open"] == 1
    assert result.iloc[0]["high"] == 2
    assert result.iloc[0]["low"] == 0
    assert result.iloc[0]["close"] == 1.5
    assert result.iloc[0]["volume"] == 1
    assert result.iloc[1]["volume"] == 2 + 3 + 4


def test_json_safe_removes_non_finite_numbers():
    assert _json_safe({"nan": np.nan, "inf": np.inf, "ok": np.float64(2.5)}) == {
        "nan": None, "inf": None, "ok": 2.5,
    }
