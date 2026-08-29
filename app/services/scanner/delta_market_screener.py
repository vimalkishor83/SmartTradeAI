"""
Delta Exchange India flexible market screener — a WHERE-condition filter over
a per-contract metric universe (price, 24h change, 24h volume, RSI(14),
funding, open interest), modelled on the standard crypto-screener UX (e.g.
Cryptomaty's Technical Scanner "24h stats" mode): stackable conditions
combined with AND/OR, one-click presets, and an asset-type scope — rather
than the Delta Scanner's fixed EMA+Supertrend BUY/SELL algorithm.

Two-tier design, same idea as delta_mtf_scanner.py's caching:
  1. _compute_universe(asset_type) — the EXPENSIVE part (bulk tickers, plus
     one 1h-candle fetch per symbol for RSI(14)) — cached for
     UNIVERSE_CACHE_TTL seconds and refreshed by a scheduler prewarm job, so
     page loads never wait on it.
  2. run_screener(...) — filters the cached universe in-memory against
     user-supplied conditions. Cheap: no network calls, so every distinct
     filter combination a user tries is instant rather than re-fetching.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.services.scanner.delta_bubbles import _get_tickers
from app.services.scanner.delta_mtf_scanner import _get_candles
from app.services.indicators.calculator import calculate_rsi

ASSET_TYPES = ("perpetual_futures", "spot", "move_options")

FIELDS = {
    "price": "Price (last)",
    "change_24h_pct": "24h change %",
    "volume_24h": "24h volume",
    "rsi_14": "RSI(14)",
    "funding_pct": "Funding %",
    "open_interest": "Open interest",
}

OPERATORS = (">", "<", ">=", "<=", "==", "between")

# Canned filter presets — the frontend can also build these client-side, but
# defining them here too means the API contract for "apply preset X" is
# stable even if the UI changes.
PRESETS = {
    "oversold": {"label": "Oversold · RSI < 30", "conditions": [{"field": "rsi_14", "op": "<", "value": 30}]},
    "overbought": {"label": "Overbought · RSI > 70", "conditions": [{"field": "rsi_14", "op": ">", "value": 70}]},
    "high_funding": {"label": "High funding · ≥ 0.05%", "conditions": [{"field": "funding_pct", "op": ">=", "value": 0.05}]},
    "top_volume": {"label": "Top volume · ≥ $100M", "conditions": [{"field": "volume_24h", "op": ">=", "value": 100_000_000}]},
    "big_movers": {"label": "Big movers · |24h| ≥ 8%", "conditions": [{"field": "change_24h_pct", "op": ">=", "value": 8, "abs": True}]},
}


def _pct_change(open_: float, close: float) -> float:
    if not open_:
        return 0.0
    return (close - open_) / open_ * 100


def _rsi_for_symbol(symbol: str) -> float | None:
    df = _get_candles(symbol, "1h", 100)
    if df is None or len(df) < 20:
        return None
    rsi = calculate_rsi(df["close"], 14)
    if rsi.empty or rsi.isna().all():
        return None
    val = rsi.iloc[-1]
    return None if val != val else round(float(val), 2)  # NaN check without importing numpy/pandas here


def _compute_universe(asset_type: str, max_workers: int = 16) -> list[dict]:
    tickers = _get_tickers(asset_type)
    candidates = [t for t in tickers if t.get("symbol") and float(t.get("close") or 0) > 0]

    rsi_by_symbol: dict[str, float | None] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_rsi_for_symbol, t["symbol"]): t["symbol"] for t in candidates}
        for fut in as_completed(futures):
            symbol = futures[fut]
            try:
                rsi_by_symbol[symbol] = fut.result()
            except Exception:
                rsi_by_symbol[symbol] = None

    universe = []
    for t in candidates:
        symbol = t["symbol"]
        close = float(t.get("close") or 0)
        open_ = float(t.get("open") or 0)
        universe.append({
            "symbol": symbol,
            "description": t.get("description") or symbol,
            "price": close,
            "change_24h_pct": round(_pct_change(open_, close), 3),
            "volume_24h": float(t.get("volume") or 0),
            "turnover_usd": float(t.get("turnover_usd") or t.get("turnover") or 0),
            "rsi_14": rsi_by_symbol.get(symbol),
            "funding_pct": _safe_pct(t.get("funding_rate")),
            "open_interest": float(t.get("oi_value_usd") or 0),
        })
    return universe


def _safe_pct(v) -> float | None:
    """Delta's funding_rate is a fractional string (e.g. "-0.0198" = -1.98%
    on perpetuals, but move_options/spot report it near 0) — convert to a
    percentage the same way the rest of the UI expects (e.g. "+0.0097%")."""
    if v is None:
        return None
    try:
        return round(float(v) * 100, 4)
    except (TypeError, ValueError):
        return None


def _match(row: dict, cond: dict) -> bool:
    field = cond.get("field")
    op = cond.get("op")
    value = cond.get("value")
    actual = row.get(field)
    if actual is None or value is None:
        return False
    if cond.get("abs"):
        actual = abs(actual)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False

    if op == ">":
        return actual > value
    if op == "<":
        return actual < value
    if op == ">=":
        return actual >= value
    if op == "<=":
        return actual <= value
    if op == "==":
        return actual == value
    if op == "between":
        try:
            value2 = float(cond.get("value2"))
        except (TypeError, ValueError):
            return False
        lo, hi = sorted((value, value2))
        return lo <= actual <= hi
    return False


def run_screener(universe: list[dict], conditions: list[dict], combinator: str = "AND") -> list[dict]:
    """Filter a precomputed universe against user conditions.

    No network calls — this is the cheap, instant part callers hit on every
    filter change. `conditions` with no valid field/op/value entries matches
    everything (mirrors "no conditions yet — every coin matches").
    """
    valid = [c for c in conditions if c.get("field") in FIELDS and c.get("op") in OPERATORS]
    if not valid:
        return list(universe)

    combine_any = combinator.upper() == "OR"
    results = []
    for row in universe:
        outcomes = [_match(row, c) for c in valid]
        matched = any(outcomes) if combine_any else all(outcomes)
        if matched:
            results.append(row)
    return results
