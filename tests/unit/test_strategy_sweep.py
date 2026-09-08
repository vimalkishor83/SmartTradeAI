import numpy as np
import pandas as pd

from app.services.backtesting.sweep import (
    SWEEP_STRATEGIES,
    SWEEP_TIMEFRAMES,
    _json_safe,
    resample_ohlcv,
)
from app.services.ai.predictor import _directional_entry_zone
from app.services.backtesting.ai_insights import (
    run_ai_insights_backtest,
    training_positions_for_checkpoint,
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


def test_ai_walk_forward_purges_unresolved_future_labels():
    positions = np.arange(20)
    labels = np.ones(20, dtype=float)
    labels[3] = np.nan

    result = training_positions_for_checkpoint(
        positions, labels, checkpoint=15, purge_bars=10,
    )

    assert result.tolist() == [0, 1, 2, 4, 5]
    assert result.max() <= 5


def test_ai_entry_zone_matches_directional_page_guidance():
    assert _directional_entry_zone(100, 10, "bullish") == (96.5, 99.5)
    assert _directional_entry_zone(100, 10, "bearish") == (100.5, 103.5)
    assert _directional_entry_zone(100, 10, "neutral") == (None, None)


def test_ai_backtest_records_walk_forward_diagnostics_without_live_artifacts(monkeypatch):
    import app.services.backtesting.ai_insights as ai_module

    index = pd.date_range("2026-01-01", periods=240, freq="h")
    close = 100 + np.sin(np.arange(240) / 5) * 4 + np.arange(240) * 0.02
    frame = pd.DataFrame({
        "open": close - 0.2,
        "high": close + 0.8,
        "low": close - 0.8,
        "close": close,
        "volume": 1000.0 + (np.arange(240) % 17) * 25.0,
    }, index=index)

    # Keep this unit test deterministic and lightweight; the server run uses
    # the real RF/XGBoost/LightGBM members when they are installed.
    monkeypatch.setattr(ai_module, "_fit_calibrated_models", lambda *_args: [])
    result = run_ai_insights_backtest(
        frame,
        type("Asset", (), {"symbol": "SOLUSDT"})(),
        "1h",
        retrain_every=50,
    )

    assert "error" not in result
    assert result["reproducibility"]["model_version"] == "ensemble-calibrated-v2"
    assert result["ai_diagnostics"]["training_label"] == "triple_barrier"
    assert result["ai_diagnostics"]["entry_fill_assumption"].startswith("market at signal close")
