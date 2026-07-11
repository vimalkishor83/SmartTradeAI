"""
Walk-forward validation: splits historical data into sequential
in-sample/out-of-sample windows and runs the SAME BacktestEngine on each,
so a strategy's edge can be checked for consistency across time rather
than trusting a single full-history backtest number (which is exactly
what overfitting to one historical stretch looks like -- a great total
return that never would have survived being deployed piece by piece).

No parameter optimization happens here (none of the three simple
strategies or multi_factor currently expose tunable parameters -- see
the module note in backtesting/engine.py) -- this is walk-forward
EVALUATION: same fixed strategy, run consistently across N consecutive
windows, comparing whether performance holds up out-of-sample-style
across different historical regimes instead of being backtested once
over the whole stretch and reported as if it were one coherent result.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.backtesting.engine import backtest_engine

_MIN_WINDOW_BARS = 150  # below this, indicator warmup dominates and results are noise


def run_walk_forward(
    df: pd.DataFrame,
    asset,
    timeframe: str,
    initial_capital: float = 100_000,
    strategy: str = "multi_factor",
    commission: float = 0.001,
    slippage: float = 0.0005,
    n_windows: int = 5,
) -> dict:
    """
    Splits df into n_windows consecutive, non-overlapping segments and runs
    backtest_engine.run() independently on each (each window gets its own
    fresh initial_capital -- these are NOT compounded across windows,
    since the point is to compare each window's stats side by side, not
    to simulate one continuous multi-window equity curve).

    Returns per-window stats plus aggregate consistency metrics: how many
    windows were net-profitable, the spread (std dev) of win_rate and
    net_profit_pct across windows, and a "walk_forward_consistent" flag
    (True only if a majority of windows were profitable AND the worst
    window's drawdown wasn't catastrophic) -- a strategy that's wildly
    profitable in 1 of 5 windows and a wipeout in the other 4 should not
    read the same as one that's modestly profitable in all 5.
    """
    if df is None or len(df) < _MIN_WINDOW_BARS * 2:
        return {"error": f"Insufficient data for walk-forward validation (need >= {_MIN_WINDOW_BARS * 2} candles)"}

    n = len(df)
    window_size = n // n_windows
    if window_size < _MIN_WINDOW_BARS:
        # Fewer, larger windows instead of erroring outright — still useful
        # with less granularity when history is on the shorter side.
        n_windows = max(2, n // _MIN_WINDOW_BARS)
        window_size = n // n_windows

    windows = []
    for w in range(n_windows):
        start = w * window_size
        end = n if w == n_windows - 1 else (w + 1) * window_size
        segment = df.iloc[start:end]
        if len(segment) < _MIN_WINDOW_BARS:
            continue

        result = backtest_engine.run(
            segment, asset, timeframe, initial_capital,
            strategy=strategy, commission=commission, slippage=slippage,
        )
        if "error" in result:
            continue

        windows.append({
            "window_index": w,
            "start_date": str(segment.index[0]) if hasattr(segment.index[0], "__str__") else str(start),
            "end_date": str(segment.index[-1]) if hasattr(segment.index[-1], "__str__") else str(end),
            "candles": len(segment),
            "total_trades": result["total_trades"],
            "win_rate": result["win_rate"],
            "net_profit_pct": result["net_profit_pct"],
            "max_drawdown": result["max_drawdown"],
            "sharpe_ratio": result["sharpe_ratio"],
            "profit_factor": result["profit_factor"],
        })

    if not windows:
        return {"error": "No window produced a valid backtest result"}

    profitable = [w for w in windows if w["net_profit_pct"] > 0]
    net_profit_pcts = [w["net_profit_pct"] for w in windows]
    win_rates = [w["win_rate"] for w in windows]
    worst_drawdown = max((w["max_drawdown"] for w in windows), default=0)

    # "Consistent" bar: profitable in a majority of windows AND no single
    # window's drawdown blew past 40% -- a strategy that's only profitable
    # because of one lucky window, or that occasionally implodes, isn't
    # something a live-money user should treat as validated just because
    # the FULL-HISTORY backtest number looked good.
    majority_profitable = len(profitable) >= (len(windows) / 2)
    consistent = majority_profitable and worst_drawdown < 40.0

    return {
        "strategy": strategy,
        "n_windows": len(windows),
        "windows": windows,
        "windows_profitable": len(profitable),
        "avg_net_profit_pct": round(float(np.mean(net_profit_pcts)), 2),
        "std_net_profit_pct": round(float(np.std(net_profit_pcts)), 2),
        "avg_win_rate": round(float(np.mean(win_rates)), 2),
        "worst_max_drawdown": round(worst_drawdown, 2),
        "walk_forward_consistent": consistent,
    }
