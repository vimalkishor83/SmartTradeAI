"""Regression tests for walk-forward aggregate statistics."""

import pandas as pd

from app.services.backtesting import walk_forward


def _frame(rows=300):
    index = pd.date_range("2026-01-01", periods=rows, freq="h")
    return pd.DataFrame({"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}, index=index)


def test_win_rate_is_weighted_by_trade_count(monkeypatch):
    results = iter([
        {"total_trades": 1, "winning_trades": 0, "win_rate": 0.0, "net_profit_pct": -1.0,
         "max_drawdown": 1.0, "sharpe_ratio": 0.0, "profit_factor": 0.0},
        {"total_trades": 9, "winning_trades": 9, "win_rate": 100.0, "net_profit_pct": 1.0,
         "max_drawdown": 1.0, "sharpe_ratio": 0.0, "profit_factor": 999.0},
    ])

    monkeypatch.setattr(walk_forward.backtest_engine, "run", lambda *args, **kwargs: next(results))

    summary = walk_forward.run_walk_forward(_frame(), asset=None, timeframe="1h", n_windows=2)

    assert summary["avg_win_rate"] == 90.0
    assert summary["total_trades"] == 10
    assert summary["winning_trades"] == 9


def test_win_rate_falls_back_to_window_rate_for_legacy_results(monkeypatch):
    results = iter([
        {"total_trades": 2, "win_rate": 50.0, "net_profit_pct": 1.0,
         "max_drawdown": 1.0, "sharpe_ratio": 0.0, "profit_factor": 1.0},
        {"total_trades": 2, "win_rate": 0.0, "net_profit_pct": -1.0,
         "max_drawdown": 1.0, "sharpe_ratio": 0.0, "profit_factor": 0.0},
    ])

    monkeypatch.setattr(walk_forward.backtest_engine, "run", lambda *args, **kwargs: next(results))

    summary = walk_forward.run_walk_forward(_frame(), asset=None, timeframe="1h", n_windows=2)

    assert summary["avg_win_rate"] == 25.0
