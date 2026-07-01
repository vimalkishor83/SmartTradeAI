"""
Walk-forward backtest runner.

Replays historical OHLCV through the *live* signal engine and simulates
whether each generated signal would have hit its target or stop first.
This is the source of truth for tuning: it proves the real win rate,
average return per trade (in R multiples), and profit factor per timeframe,
using the same logic that runs in production.

Method (avoids look-ahead bias):
  For each bar i (after a warm-up window), feed df[:i+1] to the engine as if
  bar i were the most recent closed candle. If a signal fires, walk forward
  bar-by-bar through df[i+1:] until either target1 or stop_loss is touched,
  or the per-timeframe expiry window (in bars) elapses. Record the outcome.
"""
from __future__ import annotations

import logging

import pandas as pd

from app.services.signals.engine import signal_engine, _EXPIRY
from app.services.data.fetcher import market_fetcher

logger = logging.getLogger(__name__)

# Bar duration in minutes per timeframe — used to convert the engine's
# minute-based expiry into a bar count for the forward simulation.
_TF_MINUTES = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "1d": 1440,
}

# Warm-up: enough bars for the engine's indicators before the first signal.
_WARMUP = 120


def _expiry_bars(timeframe: str) -> int:
    """How many forward bars a signal has to reach its target before expiring."""
    tf_min = _TF_MINUTES.get(timeframe, 60)
    exp_min = _EXPIRY.get(timeframe, 60)
    return max(1, round(exp_min / tf_min))


def _simulate_forward(future: pd.DataFrame, direction: str,
                      target: float, stop: float, max_bars: int) -> dict:
    """
    Walk forward bar-by-bar. Return the outcome once target or stop is touched,
    or 'expired' if neither happens within max_bars.

    Conservative tie-break: if a single bar's range spans BOTH target and stop,
    assume the stop was hit first (pessimistic — never inflates the win rate).
    """
    bars = future.head(max_bars)
    for _, bar in bars.iterrows():
        high = float(bar["high"])
        low = float(bar["low"])

        if direction in ("BUY", "HOLD"):
            hit_sl = low <= stop
            hit_tp = high >= target
            if hit_sl and hit_tp:
                return {"outcome": "loss", "exit": stop}   # pessimistic
            if hit_sl:
                return {"outcome": "loss", "exit": stop}
            if hit_tp:
                return {"outcome": "win", "exit": target}
        else:  # SELL / EXIT
            hit_sl = high >= stop
            hit_tp = low <= target
            if hit_sl and hit_tp:
                return {"outcome": "loss", "exit": stop}   # pessimistic
            if hit_sl:
                return {"outcome": "loss", "exit": stop}
            if hit_tp:
                return {"outcome": "win", "exit": target}

    # Neither target nor stop reached within the window
    last_close = float(bars["close"].iloc[-1]) if len(bars) else None
    return {"outcome": "expired", "exit": last_close}


def _summarize(trades: list[dict]) -> dict:
    """Aggregate a list of simulated trades into proven performance stats."""
    total = len(trades)
    wins = [t for t in trades if t["outcome"] == "win"]
    losses = [t for t in trades if t["outcome"] == "loss"]
    expired = [t for t in trades if t["outcome"] == "expired"]

    decided = len(wins) + len(losses)
    # Directional win rate excludes undecided (expired) trades — the honest metric.
    win_rate = round(len(wins) / decided * 100, 1) if decided else 0.0
    # Raw win rate keeps expired in the denominator (matches the live dashboard).
    raw_win_rate = round(len(wins) / total * 100, 1) if total else 0.0

    r_values = [t["r"] for t in trades if t.get("r") is not None]
    avg_r = round(sum(r_values) / len(r_values), 2) if r_values else 0.0

    gross_win = sum(t["r"] for t in wins if t.get("r"))
    gross_loss = abs(sum(t["r"] for t in losses if t.get("r")))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss else (gross_win if gross_win else 0.0)

    pnls = [t["pnl_pct"] for t in trades if t.get("pnl_pct") is not None]
    avg_pnl = round(sum(pnls) / len(pnls), 2) if pnls else 0.0

    return {
        "trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "expired": len(expired),
        "win_rate": win_rate,               # wins / (wins + losses)
        "raw_win_rate": raw_win_rate,       # wins / all (incl. expired)
        "avg_r": avg_r,                     # average return in R multiples
        "avg_pnl_pct": avg_pnl,             # average % move per trade
        "profit_factor": profit_factor,
        "expectancy_r": avg_r,             # R-based expectancy per trade
    }


def run_backtest(asset, timeframe: str, days: int = 60, limit: int | None = None) -> dict:
    """
    Backtest one asset+timeframe. Returns proven stats plus a sample of trades.

    `days` is advisory — actual depth is bounded by how much history the
    provider returns. `limit` overrides the number of candles requested.
    """
    tf_min = _TF_MINUTES.get(timeframe, 60)
    # Enough candles to cover the requested window plus warm-up.
    want = limit or min(1000, _WARMUP + int(days * 24 * 60 / tf_min))
    df = market_fetcher.fetch(asset, timeframe, limit=want)

    if df is None or len(df) < _WARMUP + 10:
        return {
            "asset": getattr(asset, "symbol", "?"),
            "timeframe": timeframe,
            "error": "insufficient historical data",
            "candles": 0 if df is None else len(df),
            **_summarize([]),
        }

    df = df.reset_index(drop=True)
    max_bars = _expiry_bars(timeframe)
    trades: list[dict] = []

    # Walk forward. Skip ahead by a small step to avoid clustered duplicate
    # signals on adjacent bars and to keep runtime reasonable.
    step = 1
    i = _WARMUP
    n = len(df)
    while i < n - 2:
        window = df.iloc[: i + 1]
        # force=True so the backtest is not blocked by the live session gate
        # (historical bars are outside "now"); this isolates the entry logic.
        sig = signal_engine.generate_signal(window, asset, timeframe, force=True)
        if not sig:
            i += step
            continue

        direction = sig["signal_type"]
        entry = float(sig["entry_price"])
        target = float(sig["target1"])
        stop = float(sig["stop_loss"])
        risk = abs(entry - stop)

        future = df.iloc[i + 1:]
        res = _simulate_forward(future, direction, target, stop, max_bars)

        exit_price = res.get("exit")
        if exit_price is not None and entry:
            if direction in ("BUY", "HOLD"):
                pnl_pct = (exit_price - entry) / entry * 100
            else:
                pnl_pct = (entry - exit_price) / entry * 100
            r = ((exit_price - entry) if direction in ("BUY", "HOLD")
                 else (entry - exit_price)) / risk if risk else None
        else:
            pnl_pct = None
            r = None

        trades.append({
            "outcome": res["outcome"],
            "direction": direction,
            "entry": round(entry, 6),
            "target": round(target, 6),
            "stop": round(stop, 6),
            "exit": round(exit_price, 6) if exit_price is not None else None,
            "pnl_pct": round(pnl_pct, 3) if pnl_pct is not None else None,
            "r": round(r, 3) if r is not None else None,
            "confidence": sig.get("confidence_score"),
        })

        # Jump past the trade's window so we don't re-enter the same move.
        i += max(step, max_bars)

    summary = _summarize(trades)
    return {
        "asset": getattr(asset, "symbol", "?"),
        "market": getattr(asset, "market", None),
        "timeframe": timeframe,
        "candles": n,
        "expiry_bars": max_bars,
        **summary,
        "sample_trades": trades[-15:],   # last few for inspection
    }


def backtest_portfolio(assets, timeframe: str, days: int = 60) -> dict:
    """
    Run the backtest across many assets and aggregate. Returns per-asset
    results plus a combined summary and a per-market breakdown.
    """
    per_asset = []
    all_trades: list[dict] = []
    by_market: dict[str, list[dict]] = {}

    for asset in assets:
        try:
            res = run_backtest(asset, timeframe, days=days)
        except Exception as e:
            logger.error(f"Backtest failed for {getattr(asset, 'symbol', '?')}: {e}")
            continue
        per_asset.append(res)

        # Rebuild trade list for aggregation from the summary counts is lossy,
        # so re-run is avoided by aggregating the summary stats directly below.
        mkt = res.get("market") or "unknown"
        by_market.setdefault(mkt, []).append(res)

    def _agg(results: list[dict]) -> dict:
        t = sum(r["trades"] for r in results)
        w = sum(r["wins"] for r in results)
        l = sum(r["losses"] for r in results)
        e = sum(r["expired"] for r in results)
        decided = w + l
        avg_r = round(sum(r["avg_r"] * r["trades"] for r in results) / t, 2) if t else 0.0
        return {
            "trades": t, "wins": w, "losses": l, "expired": e,
            "win_rate": round(w / decided * 100, 1) if decided else 0.0,
            "raw_win_rate": round(w / t * 100, 1) if t else 0.0,
            "avg_r": avg_r,
        }

    market_breakdown = {mkt: _agg(rs) for mkt, rs in by_market.items()}

    return {
        "timeframe": timeframe,
        "days": days,
        "assets_tested": len(per_asset),
        "overall": _agg(per_asset) if per_asset else _summarize([]),
        "by_market": market_breakdown,
        "per_asset": sorted(per_asset, key=lambda r: r.get("win_rate", 0), reverse=True),
    }
