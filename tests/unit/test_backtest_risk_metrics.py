"""Regression coverage for risk metrics in the strategy-config backtest."""

import pandas as pd
import pytest

from app.services.backtesting.engine import (
    BacktestEngine,
    _annualized_risk_metrics,
)


engine = BacktestEngine()


def _trade(pnl=20.0, pnl_pct=20.0):
    return {
        "entry": 100.0,
        "exit": 120.0,
        "type": "BUY",
        "bars_held": 1,
        "exit_reason": "target2",
        "pnl_pct": pnl_pct,
        "pnl": pnl,
        "commission": 0.0,
        "slippage_cost": 0.0,
        "spread_cost": 0.0,
        "outcome": "win",
        "date": "2026-01-01",
    }


def test_risk_ratios_use_equity_bar_returns_and_zero_target_downside():
    equity = [100.0, 101.0, 101.0, 100.0]
    returns = pd.Series(equity).pct_change().dropna()
    annualization = _annualized_risk_metrics(equity, "1d")

    expected_sharpe = returns.mean() / returns.std(ddof=1) * (252 ** 0.5)
    downside = returns.clip(upper=0)
    expected_sortino = returns.mean() / (downside.pow(2).mean() ** 0.5) * (252 ** 0.5)

    assert annualization[0] == pytest.approx(expected_sharpe)
    assert annualization[1] == pytest.approx(expected_sortino)


def test_compute_stats_reports_recovery_factor_from_money_drawdown():
    stats = engine._compute_stats(
        [_trade()],
        [100.0, 110.0, 105.0, 120.0],
        100.0,
        0.0,
        0.0,
        "1d",
    )

    assert stats["max_drawdown"] == pytest.approx(-4.55, abs=0.01)
    assert stats["recovery_factor"] == 4.0


def test_recovery_factor_uses_explicit_cap_without_observed_drawdown():
    stats = engine._compute_stats(
        [_trade()],
        [100.0, 101.0, 102.0],
        100.0,
        0.0,
        0.0,
        "1d",
    )

    assert stats["max_drawdown"] == 0.0
    assert stats["recovery_factor"] == 999.0
