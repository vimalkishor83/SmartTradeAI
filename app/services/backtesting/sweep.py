"""Server-side strategy matrix backtesting and report assembly."""
from __future__ import annotations

from datetime import datetime
import math
from typing import Any

import numpy as np
import pandas as pd

from app.services.backtesting.engine import backtest_engine
from app.services.backtesting.reproducibility import BACKTEST_ENGINE_VERSION
from app.services.data.fetcher import market_fetcher


SWEEP_TIMEFRAMES = ("5m", "15m", "30m", "1h", "2h", "3h", "1d")
SWEEP_STRATEGIES = (
    {
        "key": "rsi",
        "label": "RSI Mean Reversion",
        "description": "Oversold/overbought RSI reversal with price confirmation.",
    },
    {
        "key": "macd",
        "label": "MACD Crossover",
        "description": "MACD line and signal-line crossover entries.",
    },
    {
        "key": "ema_crossover",
        "label": "EMA Crossover",
        "description": "EMA 20/50 trend crossover entries.",
    },
    {
        "key": "multi_factor",
        "label": "Multi-Factor Live Engine",
        "description": "The live signal pipeline, including trend, momentum, volume, pattern, and risk gates.",
    },
)

SWEEP_CANDLE_LIMIT = 400
SWEEP_INITIAL_CAPITAL = 100_000.0
SWEEP_COMMISSION = 0.001
SWEEP_SLIPPAGE = 0.0005
SWEEP_SPREAD = 0.0


def sweep_strategy_catalog() -> list[dict[str, str]]:
    return [dict(item) for item in SWEEP_STRATEGIES]


def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Build a deterministic OHLCV frame for a derived timeframe."""
    if timeframe != "3h" or df is None or df.empty:
        return df
    frame = df.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index)
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    aggregated = frame.resample("3h", origin="epoch", label="right", closed="right").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    return aggregated.dropna(subset=["open", "high", "low", "close"])


def fetch_sweep_frame(asset, timeframe: str, candle_limit: int = SWEEP_CANDLE_LIMIT) -> pd.DataFrame | None:
    """Fetch only the requested frame and release the provider's raw frame later.

    Three-hour candles are derived from hourly candles because Delta/Binance do
    not expose a native 3h interval in this project.
    """
    if timeframe == "3h":
        base_limit = max(candle_limit * 3 + 12, 180)
        base = market_fetcher.fetch(asset, "1h", base_limit)
        return resample_ohlcv(base, "3h").tail(candle_limit) if base is not None else None
    return market_fetcher.fetch(asset, timeframe, candle_limit)


def _json_safe(value: Any):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _score_result(stats: dict) -> float | None:
    """A comparison hint, not a promise of future trading performance."""
    trades = int(stats.get("total_trades") or 0)
    if trades < 5:
        return None
    return round(
        float(stats.get("net_profit_pct") or 0)
        - abs(float(stats.get("max_drawdown") or 0)) * 0.5
        + min(float(stats.get("profit_factor") or 0), 10) * 2
        + min(float(stats.get("win_rate") or 0), 100) * 0.02,
        2,
    )


def _cell_record(asset, timeframe: str, strategy: dict, df: pd.DataFrame, result: dict) -> dict:
    stats = {
        key: result.get(key)
        for key in (
            "total_trades", "winning_trades", "losing_trades", "win_rate",
            "net_profit", "net_profit_pct", "max_drawdown", "sharpe_ratio",
            "sortino_ratio", "recovery_factor", "profit_factor", "avg_win",
            "avg_loss", "avg_bars_held", "total_commission", "total_slippage",
            "total_spread", "exit_reasons",
        )
    }
    stats["comparison_score"] = _score_result(stats)
    provenance = result.get("reproducibility") or {}
    return _json_safe(
        {
            "asset": asset.symbol,
            "asset_name": getattr(asset, "name", None) or asset.symbol,
            "timeframe": timeframe,
            "data_mode": "derived_from_1h" if timeframe == "3h" else "native_provider",
            "strategy": strategy["key"],
            "strategy_label": strategy["label"],
            "description": strategy["description"],
            "status": "completed",
            "candles": len(df),
            "data_start": provenance.get("data_start") or str(df.index[0]),
            "data_end": provenance.get("data_end") or str(df.index[-1]),
            "data_fingerprint": provenance.get("data_fingerprint"),
            "stats": stats,
            # The report needs enough data to inspect shape and recent fills,
            # not a second database full of every intermediate candle.
            "equity_curve": result.get("equity_curve", [])[-160:],
            "trades": result.get("trades_data", [])[-30:],
        }
    )


def _error_record(asset, timeframe: str, strategy: dict, error: str) -> dict:
    return {
        "asset": asset.symbol,
        "asset_name": getattr(asset, "name", None) or asset.symbol,
        "timeframe": timeframe,
        "data_mode": "derived_from_1h" if timeframe == "3h" else "native_provider",
        "strategy": strategy["key"],
        "strategy_label": strategy["label"],
        "status": "failed",
        "error": str(error)[:500],
    }


def _build_summary(cells: list[dict]) -> dict:
    completed = [cell for cell in cells if cell.get("status") == "completed"]
    eligible = [cell for cell in completed if cell.get("stats", {}).get("comparison_score") is not None]
    ranked = sorted(eligible, key=lambda cell: cell["stats"]["comparison_score"], reverse=True)
    by_asset: dict[str, dict] = {}
    for cell in ranked:
        by_asset.setdefault(cell["asset"], cell)
    return {
        "completed_cells": len(completed),
        "failed_cells": len(cells) - len(completed),
        "eligible_cells": len(eligible),
        "best_overall": {
            "asset": ranked[0]["asset"],
            "timeframe": ranked[0]["timeframe"],
            "strategy": ranked[0]["strategy_label"],
            "comparison_score": ranked[0]["stats"]["comparison_score"],
        } if ranked else None,
        "best_by_asset": {
            asset: {
                "timeframe": cell["timeframe"],
                "strategy": cell["strategy_label"],
                "comparison_score": cell["stats"]["comparison_score"],
                "net_profit_pct": cell["stats"].get("net_profit_pct"),
                "win_rate": cell["stats"].get("win_rate"),
                "max_drawdown": cell["stats"].get("max_drawdown"),
            }
            for asset, cell in by_asset.items()
        },
    }


def run_strategy_sweep(sweep, assets, *, candle_limit=SWEEP_CANDLE_LIMIT):
    """Run and persist the matrix sequentially so progress survives failures."""
    from app.extensions import db

    strategies = sweep_strategy_catalog()
    cells = list((sweep.result_data or {}).get("cells") or [])
    errors = list(sweep.errors or [])
    completed_keys = {
        (cell.get("asset"), cell.get("timeframe"), cell.get("strategy"))
        for cell in cells
        if cell.get("status") == "completed"
    }
    sweep.status = "running"
    sweep.started_at = sweep.started_at or datetime.utcnow()
    sweep.total_cells = len(assets) * len(SWEEP_TIMEFRAMES) * len(strategies)
    sweep.candle_limit = candle_limit
    sweep.engine_version = BACKTEST_ENGINE_VERSION
    sweep.result_data = {"cells": cells}
    db.session.commit()

    for asset in assets:
        for timeframe in SWEEP_TIMEFRAMES:
            try:
                df = fetch_sweep_frame(asset, timeframe, candle_limit)
            except Exception as exc:
                df = None
                fetch_error = f"data fetch failed: {exc}"
            else:
                fetch_error = "No market data returned"

            for strategy in strategies:
                key = (asset.symbol, timeframe, strategy["key"])
                if key in completed_keys:
                    continue
                try:
                    if df is None or len(df) < 100:
                        raise ValueError(f"{fetch_error}; received {len(df) if df is not None else 0} candles")
                    result = backtest_engine.run(
                        df,
                        asset,
                        timeframe,
                        sweep.initial_capital,
                        strategy=strategy["key"],
                        commission=sweep.commission,
                        slippage=sweep.slippage,
                        spread=sweep.spread,
                    )
                    if "error" in result:
                        raise ValueError(result["error"])
                    cell = _cell_record(asset, timeframe, strategy, df, result)
                except Exception as exc:
                    cell = _error_record(asset, timeframe, strategy, exc)
                    errors.append(cell)
                cells.append(cell)
                sweep.completed_cells = len(cells)
                sweep.result_data = {"cells": cells}
                sweep.summary = _build_summary(cells)
                sweep.errors = errors[-100:]
                db.session.commit()

    sweep.status = "completed" if not errors else "completed_with_errors"
    sweep.completed_at = datetime.utcnow()
    sweep.result_data = {"cells": _json_safe(cells)}
    sweep.summary = _build_summary(cells)
    sweep.errors = _json_safe(errors[-100:])
    db.session.commit()
    return sweep
