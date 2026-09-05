"""Regression coverage for stable backtest fingerprints."""

import pandas as pd
from types import SimpleNamespace

from app.services.backtesting.reproducibility import (
    BACKTEST_ENGINE_VERSION,
    MODEL_VERSION,
    build_reproducibility_metadata,
    config_fingerprint,
    data_fingerprint,
)


def _frame(rows=3, close=100.0):
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0},
        index=pd.date_range("2026-01-01", periods=rows, freq="h"),
    )


def test_fingerprints_are_stable_and_change_with_inputs():
    frame = _frame()
    same = _frame()

    assert data_fingerprint(frame) == data_fingerprint(same)
    assert data_fingerprint(frame) != data_fingerprint(_frame(close=101.0))
    assert config_fingerprint(
        strategy="rsi", timeframe="1h", initial_capital=10_000,
        commission=0.001, slippage=0.0005,
    ) != config_fingerprint(
        strategy="rsi", timeframe="1h", initial_capital=10_000,
        commission=0.002, slippage=0.0005,
    )


def test_reproducibility_metadata_has_explicit_model_scope():
    metadata = build_reproducibility_metadata(
        _frame(),
        strategy="rsi",
        timeframe="1h",
        initial_capital=10_000,
        commission=0.001,
        slippage=0.0005,
    )

    assert metadata["backtest_id"] is None
    assert metadata["engine_version"] == BACKTEST_ENGINE_VERSION
    assert metadata["model_version"] == MODEL_VERSION == "not_applicable"
    assert metadata["data_candles"] == 3
    assert metadata["data_start"] == "2026-01-01T00:00:00"
    assert metadata["data_end"] == "2026-01-01T02:00:00"


def test_walk_forward_includes_diagnostic_provenance(monkeypatch):
    from app.services.backtesting import walk_forward

    results = iter([
        {
            "total_trades": 1, "winning_trades": 1, "win_rate": 100.0,
            "net_profit_pct": 1.0, "max_drawdown": 1.0,
            "sharpe_ratio": 0.0, "profit_factor": 1.0,
        },
        {
            "total_trades": 1, "winning_trades": 0, "win_rate": 0.0,
            "net_profit_pct": -1.0, "max_drawdown": 1.0,
            "sharpe_ratio": 0.0, "profit_factor": 0.0,
        },
    ])
    monkeypatch.setattr(
        walk_forward.backtest_engine,
        "run",
        lambda *args, **kwargs: next(results),
    )

    summary = walk_forward.run_walk_forward(
        _frame(300), asset=None, timeframe="1h", strategy="rsi", n_windows=2,
    )

    assert summary["reproducibility"]["backtest_id"] is None
    assert summary["reproducibility"]["engine_version"] == "strategy-backtest-v2"
    assert summary["reproducibility"]["data_candles"] == 300
    assert len(summary["reproducibility"]["data_fingerprint"]) == 64


def test_live_signal_runner_includes_source_dataset_provenance(monkeypatch):
    from app.services.backtest import runner

    frame = _frame(130)
    monkeypatch.setattr(runner.market_fetcher, "fetch", lambda *args, **kwargs: frame)
    monkeypatch.setattr(runner.signal_engine, "generate_signal", lambda *args, **kwargs: None)

    result = runner.run_backtest(
        SimpleNamespace(symbol="BTCUSDT", market="crypto"), "1h", days=1,
    )

    assert result["reproducibility"]["engine_version"] == "live-signal-walkforward-v1"
    assert result["reproducibility"]["model_version"] == "not_applicable"
    assert result["reproducibility"]["data_candles"] == 130
    assert result["reproducibility"]["data_start"] == "2026-01-01T00:00:00"
