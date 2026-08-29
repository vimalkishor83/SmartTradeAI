"""
Multi-timeframe EMA + Supertrend scanner for Delta Exchange contracts.

Scans every live perpetual-futures contract on Delta Exchange directly
(not the curated Asset watchlist — the spec calls for "all tradable
contracts on Delta Exchange") and ranks BUY/SELL candidates that have
full 3-timeframe confirmation:

  - 5m: price sustaining near the 9/21/50 EMA zone, with 9/21 EMA
    alignment giving the directional bias.
  - 15m and 1h: Supertrend(10, 3) direction must agree with that bias.
  - Volume/turnover strength and trend (Delta's public REST has no
    per-candle trade-count field, so recent-vs-prior 5m volume momentum
    is used as the trade-activity-strength proxy).

Only contracts meeting ALL conditions are returned — no partial or
single-indicator matches.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from app.services.data.fetcher import _http_session, _retry
from app.services.indicators.calculator import calculate_all_indicators

logger = logging.getLogger(__name__)

DELTA_BASE = "https://api.india.delta.exchange/v2"

# Price within this % of the 9/21/50 EMA cluster on the 5m chart counts as
# "sustaining near the zone"; beyond it, the setup is "excessively extended".
EMA_ZONE_MAX_DISTANCE_PCT = 1.2

CANDLES_LOOKBACK = {"5m": 200, "15m": 150, "1h": 150}
SECONDS_PER_CANDLE = {"5m": 300, "15m": 900, "1h": 3600}

# Delta's ticker "description" is a full product name (e.g. "Bitcoin
# Perpetual", "Amazon xStock Token Perpetual") — too long for a table
# column. Stripping these known Delta-specific suffixes (repeatedly, since
# several stack on one description) reduces most of them to a clean short
# name without a symbol-by-symbol lookup table.
_NAME_NOISE_SUFFIXES = (" Perpetual", " Futures", " Options", " Move", " Token", " xStock", " bStocks")

# A handful of descriptions don't reduce to a clean name via suffix-stripping
# alone (e.g. "iShares Silver (XAG) Trust ONDO Token Perpetual") — these are
# the only overrides needed; everything else falls through to the generic
# stripping above.
_NAME_OVERRIDES = {
    "XAUTUSD": "Gold",
    "PAXGUSD": "Gold",
    "SLVONUSD": "Silver",
}


def _short_name(symbol: str, description: str | None) -> str:
    if symbol in _NAME_OVERRIDES:
        return _NAME_OVERRIDES[symbol]
    name = (description or symbol).strip()
    changed = True
    while changed:
        changed = False
        for suffix in _NAME_NOISE_SUFFIXES:
            if name.endswith(suffix):
                name = name[: -len(suffix)].strip()
                changed = True
    return name or symbol


@_retry(max_attempts=3, backoff=1.5)
def _get_tickers() -> list[dict]:
    resp = _http_session.get(
        f"{DELTA_BASE}/tickers",
        params={"contract_types": "perpetual_futures"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("result", [])


@_retry(max_attempts=2, backoff=1.5)
def _get_candles(symbol: str, resolution: str, limit: int) -> pd.DataFrame | None:
    end_ts = int(time.time())
    start_ts = end_ts - SECONDS_PER_CANDLE[resolution] * limit
    resp = _http_session.get(
        f"{DELTA_BASE}/history/candles",
        params={"symbol": symbol, "resolution": resolution, "start": start_ts, "end": end_ts},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json().get("result")
    if not data:
        return None
    df = pd.DataFrame(data)
    ohlcv_cols = ["open", "high", "low", "close", "volume"]
    df[ohlcv_cols] = df[ohlcv_cols].astype(float)
    df["timestamp"] = pd.to_datetime(df["time"], unit="s")
    return df[["timestamp", *ohlcv_cols]].sort_values("timestamp").reset_index(drop=True)


def _volume_trend(df_5m: pd.DataFrame) -> tuple[str, int]:
    recent = df_5m["volume"].tail(6)
    prior = df_5m["volume"].tail(18).head(12)
    if prior.empty or prior.mean() == 0:
        return "flat", 0
    ratio = recent.mean() / prior.mean()
    if ratio >= 1.15:
        return "increasing", 2
    if ratio <= 0.85:
        return "declining", 0
    return "flat", 1


def _scan_symbol(ticker: dict) -> dict | None:
    symbol = ticker.get("symbol")
    if not symbol:
        return None

    try:
        df_5m = _get_candles(symbol, "5m", CANDLES_LOOKBACK["5m"])
        df_15m = _get_candles(symbol, "15m", CANDLES_LOOKBACK["15m"])
        df_1h = _get_candles(symbol, "1h", CANDLES_LOOKBACK["1h"])
    except Exception as e:
        logger.debug("Delta scanner: skipping %s (%s)", symbol, e)
        return None

    if df_5m is None or df_15m is None or df_1h is None:
        return None
    if len(df_5m) < 55 or len(df_15m) < 15 or len(df_1h) < 15:
        return None

    ind_5m = calculate_all_indicators(df_5m)
    ind_15m = calculate_all_indicators(df_15m)
    ind_1h = calculate_all_indicators(df_1h)
    if not ind_5m or not ind_15m or not ind_1h:
        return None

    ema9, ema21, ema50 = ind_5m.get("ema9"), ind_5m.get("ema21"), ind_5m.get("ema50")
    price = float(df_5m["close"].iloc[-1])
    st_dir_15m = ind_15m.get("supertrend_direction")
    st_dir_1h = ind_1h.get("supertrend_direction")
    st_val_15m = ind_15m.get("supertrend")
    st_val_1h = ind_1h.get("supertrend")

    if None in (ema9, ema21, ema50, st_dir_15m, st_dir_1h) or price <= 0:
        return None

    ema_zone_low, ema_zone_high = min(ema9, ema21, ema50), max(ema9, ema21, ema50)
    if price < ema_zone_low:
        zone_distance_pct = (ema_zone_low - price) / price * 100
    elif price > ema_zone_high:
        zone_distance_pct = (price - ema_zone_high) / price * 100
    else:
        zone_distance_pct = 0.0

    if zone_distance_pct > EMA_ZONE_MAX_DISTANCE_PCT:
        return None

    ema_bullish = ema9 > ema21
    ema_bearish = ema9 < ema21
    st_15m_bullish = st_dir_15m == "up"
    st_1h_bullish = st_dir_1h == "up"

    direction = None
    reasons: list[str] = []
    if ema_bullish and st_15m_bullish and st_1h_bullish:
        direction = "BUY"
        reasons = [
            "Price sustaining near 9/21/50 EMA zone on 5m",
            "9 EMA > 21 EMA (bullish momentum)",
            "15m Supertrend(10,3) bullish",
            "1h Supertrend(10,3) bullish",
        ]
    elif ema_bearish and not st_15m_bullish and not st_1h_bullish:
        direction = "SELL"
        reasons = [
            "Price sustaining near 9/21/50 EMA zone on 5m",
            "9 EMA < 21 EMA (bearish momentum)",
            "15m Supertrend(10,3) bearish",
            "1h Supertrend(10,3) bearish",
        ]
    else:
        return None

    volume_trend, volume_score = _volume_trend(df_5m)
    reasons.append(f"Volume trend: {volume_trend}")

    proximity_score = max(0, 3 - round(zone_distance_pct / (EMA_ZONE_MAX_DISTANCE_PCT / 3)))
    score = 4 + proximity_score + volume_score
    max_score = 9
    tier = "strong" if score >= 8 else "moderate" if score >= 6 else "weak"

    volume_24h = float(ticker.get("volume") or 0)
    turnover_usd = float(ticker.get("turnover_usd") or ticker.get("turnover") or 0)

    return {
        "symbol": symbol,
        "description": ticker.get("description") or symbol,
        "short_name": _short_name(symbol, ticker.get("description")),
        "direction": direction,
        "current_price": price,
        "volume_24h": volume_24h,
        "turnover_usd": turnover_usd,
        "trade_count_proxy": volume_24h,
        "ema": {"ema9": round(ema9, 6), "ema21": round(ema21, 6), "ema50": round(ema50, 6)},
        "ema_zone_distance_pct": round(float(zone_distance_pct), 3),
        "supertrend_15m": "bullish" if st_15m_bullish else "bearish",
        "supertrend_1h": "bullish" if st_1h_bullish else "bearish",
        "supertrend_15m_value": round(float(st_val_15m), 6) if st_val_15m is not None else None,
        "supertrend_1h_value": round(float(st_val_1h), 6) if st_val_1h is not None else None,
        "volume_trend": volume_trend,
        "score": score,
        "max_score": max_score,
        "tier": tier,
        "reasons": reasons,
    }


def _status_for_symbol(ticker: dict) -> dict | None:
    """Like _scan_symbol, but ALWAYS returns a status — including the
    "mixed" case _scan_symbol drops entirely — for the MTF "Common Coins"
    status panel, which needs to show a configured coin's current read even
    when it doesn't qualify as a full BUY/SELL scan hit."""
    symbol = ticker.get("symbol")
    if not symbol:
        return None
    try:
        df_5m = _get_candles(symbol, "5m", CANDLES_LOOKBACK["5m"])
        df_15m = _get_candles(symbol, "15m", CANDLES_LOOKBACK["15m"])
        df_1h = _get_candles(symbol, "1h", CANDLES_LOOKBACK["1h"])
    except Exception as e:
        logger.debug("Delta status: skipping %s (%s)", symbol, e)
        return None
    if df_5m is None or df_15m is None or df_1h is None:
        return None
    if len(df_5m) < 55 or len(df_15m) < 15 or len(df_1h) < 15:
        return None

    ind_5m = calculate_all_indicators(df_5m)
    ind_15m = calculate_all_indicators(df_15m)
    ind_1h = calculate_all_indicators(df_1h)
    if not ind_5m or not ind_15m or not ind_1h:
        return None

    ema9, ema21, ema50 = ind_5m.get("ema9"), ind_5m.get("ema21"), ind_5m.get("ema50")
    price = float(df_5m["close"].iloc[-1])
    st_dir_15m = ind_15m.get("supertrend_direction")
    st_dir_1h = ind_1h.get("supertrend_direction")
    st_val_15m = ind_15m.get("supertrend")
    st_val_1h = ind_1h.get("supertrend")
    if None in (ema9, ema21, ema50, st_dir_15m, st_dir_1h) or price <= 0:
        return None

    ema_zone_low, ema_zone_high = min(ema9, ema21, ema50), max(ema9, ema21, ema50)
    if price < ema_zone_low:
        zone_distance_pct = (ema_zone_low - price) / price * 100
    elif price > ema_zone_high:
        zone_distance_pct = (price - ema_zone_high) / price * 100
    else:
        zone_distance_pct = 0.0

    ema_bullish = ema9 > ema21
    st_15m_bullish = st_dir_15m == "up"
    st_1h_bullish = st_dir_1h == "up"

    if ema_bullish and st_15m_bullish and st_1h_bullish:
        status = "bullish"
    elif (not ema_bullish) and (not st_15m_bullish) and (not st_1h_bullish):
        status = "bearish"
    else:
        status = "mixed"  # timeframes disagree — no clean directional read right now

    volume_trend, _ = _volume_trend(df_5m)
    change_pct = 0.0
    open_ = float(ticker.get("open") or 0)
    if open_:
        change_pct = (price - open_) / open_ * 100

    return {
        "symbol": symbol,
        "description": ticker.get("description") or symbol,
        "short_name": _short_name(symbol, ticker.get("description")),
        "status": status,
        "current_price": price,
        "change_pct": round(change_pct, 3),
        "ema": {"ema9": round(ema9, 6), "ema21": round(ema21, 6), "ema50": round(ema50, 6)},
        "ema_zone_distance_pct": round(float(zone_distance_pct), 3),
        "supertrend_15m": "bullish" if st_15m_bullish else "bearish",
        "supertrend_1h": "bullish" if st_1h_bullish else "bearish",
        "supertrend_15m_value": round(float(st_val_15m), 6) if st_val_15m is not None else None,
        "supertrend_1h_value": round(float(st_val_1h), 6) if st_val_1h is not None else None,
        "volume_trend": volume_trend,
    }


def get_status_for_symbols(symbols: list[str], max_workers: int = 8) -> dict:
    """Unfiltered live status for a specific, small set of symbols — the
    MTF Scanner's configurable "Common Coins" panel. Unlike run_scan(), every
    requested symbol that has enough data gets a row back (bullish/bearish/
    mixed), not just the ones with full 3-timeframe agreement."""
    try:
        tickers = _get_tickers()
    except Exception as e:
        logger.warning("Delta status: failed to fetch tickers: %s", e)
        return {"generated_at": int(time.time()), "results": [], "message": f"Could not reach Delta Exchange: {e}"}

    by_symbol = {t.get("symbol"): t for t in tickers if t.get("symbol")}
    wanted = [by_symbol[s] for s in symbols if s in by_symbol]

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_status_for_symbol, t): t for t in wanted}
        for fut in as_completed(futures):
            r = fut.result()
            if r is not None:
                results.append(r)

    order = {s: i for i, s in enumerate(symbols)}
    results.sort(key=lambda r: order.get(r["symbol"], 999))

    return {
        "generated_at": int(time.time()),
        "results": results,
        "message": None if results else "None of the configured symbols returned data.",
    }


def list_symbols() -> list[dict]:
    """Every live Delta perpetual symbol + short display name, sorted by
    turnover — for the Common Coins search-and-select picker. No candle
    fetches, just a projection over the ticker list already needed
    elsewhere in this module."""
    try:
        tickers = _get_tickers()
    except Exception as e:
        logger.warning("Delta symbols: failed to fetch tickers: %s", e)
        return []

    rows = [
        {
            "symbol": t["symbol"],
            "short_name": _short_name(t["symbol"], t.get("description")),
            "turnover_usd": float(t.get("turnover_usd") or t.get("turnover") or 0),
        }
        for t in tickers
        if t.get("symbol")
    ]
    rows.sort(key=lambda r: r["turnover_usd"], reverse=True)
    for r in rows:
        del r["turnover_usd"]
    return rows


def run_scan(max_workers: int = 12) -> dict:
    """Scan all live Delta Exchange perpetual contracts and return ranked
    BUY/SELL lists. Safe to call from a request handler or a scheduled job."""
    try:
        tickers = _get_tickers()
    except Exception as e:
        logger.warning("Delta scanner: failed to fetch tickers: %s", e)
        return {
            "generated_at": int(time.time()),
            "contracts_scanned": 0,
            "buy": [],
            "sell": [],
            "message": f"Could not reach Delta Exchange: {e}",
        }

    candidates = [t for t in tickers if t.get("symbol") and float(t.get("volume") or 0) > 0]

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_scan_symbol, t): t for t in candidates}
        for fut in as_completed(futures):
            r = fut.result()
            if r is not None:
                results.append(r)

    buy = sorted([r for r in results if r["direction"] == "BUY"], key=lambda r: r["turnover_usd"], reverse=True)
    sell = sorted([r for r in results if r["direction"] == "SELL"], key=lambda r: r["turnover_usd"], reverse=True)

    return {
        "generated_at": int(time.time()),
        "contracts_scanned": len(candidates),
        "buy": buy,
        "sell": sell,
        "message": None if (buy or sell) else (
            "No contracts met all multi-timeframe conditions "
            "(5m EMA zone + 15m Supertrend + 1h Supertrend agreement) at this time."
        ),
    }
