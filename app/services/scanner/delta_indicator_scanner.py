"""
Delta Exchange India indicator-crossover scanner — the "Indicators" mode of
a technical scanner (modelled on Cryptomaty's Pro-tier Indicator Scanner,
see project_cryptomaty_scanner_research memory): pick a candle timeframe,
then build conditions like "EMA 9 crosses above EMA 20" or "RSI 14 is below
30", stacked with AND/OR.

Unlike delta_market_screener.py (ticker-derived fields only, cheap), this
needs the FULL OHLCV series per symbol to compute a real indicator set and
to detect a crossing (which requires the PREVIOUS closed candle's value, not
just the latest). Reuses delta_mtf_scanner.py's candle fetcher and the
shared calculator functions in app/services/indicators/calculator.py rather
than duplicating either.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from app.services.scanner.delta_bubbles import _get_tickers
from app.services.scanner.delta_mtf_scanner import _get_candles, SECONDS_PER_CANDLE
from app.services.indicators.calculator import (
    calculate_ema, calculate_sma, calculate_rsi, calculate_macd,
    calculate_atr, calculate_adx, calculate_bollinger_bands,
)

ASSET_TYPES = ("perpetual_futures", "spot", "move_options")
TIMEFRAMES = tuple(SECONDS_PER_CANDLE.keys())  # ("5m", "15m", "1h")

# Candle count per symbol fetch. 250 gives EMA200/SMA200 real warm-up rather
# than a value dominated by the too-short history they'd get with the
# ~150-200 bar lookbacks the MTF scanner uses for its own (shorter-period)
# indicators.
CANDLES_LOOKBACK = 250

INDICATORS = {
    "price": "Price",
    "volume_bar": "Volume (bar)",
    "ema9": "EMA 9",
    "ema20": "EMA 20",
    "ema50": "EMA 50",
    "ema200": "EMA 200",
    "sma20": "SMA 20",
    "sma50": "SMA 50",
    "sma200": "SMA 200",
    "rsi14": "RSI 14",
    "macd_line": "MACD line",
    "macd_signal": "MACD signal",
    "macd_hist": "MACD histogram",
    "adx14": "ADX 14",
    "atr14": "ATR 14",
    "bb_upper": "Bollinger upper",
    "bb_lower": "Bollinger lower",
    "bb_pctb": "Bollinger %B",
}

COMPARISONS = (
    "crosses_above", "crosses_below",
    "is_above", "is_below",
    "is_at_or_above", "is_at_or_below",
    "is_between",
)


def _compute_indicator_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Every field in INDICATORS as a full-length column, so callers can read
    both the latest closed value AND the one before it (needed for crossing
    detection) with plain .iloc[-1]/.iloc[-2]."""
    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]
    n = len(df)

    out = pd.DataFrame(index=df.index)
    out["price"] = close
    out["volume_bar"] = volume
    out["ema9"] = calculate_ema(close, 9)
    out["ema20"] = calculate_ema(close, 20)
    out["ema50"] = calculate_ema(close, 50) if n >= 50 else out["ema20"]
    out["ema200"] = calculate_ema(close, 200) if n >= 200 else out["ema50"]
    out["sma20"] = calculate_sma(close, 20)
    out["sma50"] = calculate_sma(close, 50) if n >= 50 else out["sma20"]
    out["sma200"] = calculate_sma(close, 200) if n >= 200 else out["sma50"]
    out["rsi14"] = calculate_rsi(close, 14)
    macd_line, macd_signal, macd_hist = calculate_macd(close)
    out["macd_line"] = macd_line
    out["macd_signal"] = macd_signal
    out["macd_hist"] = macd_hist
    out["adx14"] = calculate_adx(high, low, close, 14)
    out["atr14"] = calculate_atr(high, low, close, 14)
    bb_upper, bb_mid, bb_lower, _ = calculate_bollinger_bands(close)
    out["bb_upper"] = bb_upper
    out["bb_lower"] = bb_lower
    band_width = (bb_upper - bb_lower).replace(0, float("nan"))
    out["bb_pctb"] = (close - bb_lower) / band_width
    return out


def _last_two(frame: pd.DataFrame, field: str) -> tuple[float | None, float | None]:
    """(previous, current) closed-candle values for a field, or (None, None)
    if there isn't enough history yet."""
    col = frame[field]
    if len(col) < 2:
        return None, None
    prev, curr = col.iloc[-2], col.iloc[-1]
    prev = None if prev != prev else float(prev)  # NaN check
    curr = None if curr != curr else float(curr)
    return prev, curr


def _scan_symbol(ticker: dict, timeframe: str) -> dict | None:
    symbol = ticker.get("symbol")
    if not symbol:
        return None
    try:
        df = _get_candles(symbol, timeframe, CANDLES_LOOKBACK)
    except Exception:
        return None
    if df is None or len(df) < 25:  # need at least enough for RSI/MACD to be meaningful
        return None

    frame = _compute_indicator_frame(df)
    values: dict[str, tuple[float | None, float | None]] = {
        field: _last_two(frame, field) for field in INDICATORS
    }
    if values["price"][1] is None:
        return None

    return {
        "symbol": symbol,
        "description": ticker.get("description") or symbol,
        "turnover_usd": float(ticker.get("turnover_usd") or ticker.get("turnover") or 0),
        "values": values,  # field -> (prev, curr)
    }


def _operand_value(row: dict, operand: dict) -> tuple[float | None, float | None]:
    """Resolve one side of a condition to (prev, curr). A numeric operand has
    the same value on both sides — a "crosses above 30" condition treats 30
    as a flat line, which is exactly what a static threshold means."""
    if operand.get("type") == "number":
        try:
            v = float(operand["value"])
        except (TypeError, ValueError, KeyError):
            return None, None
        return v, v
    field = operand.get("field")
    if field not in row["values"]:
        return None, None
    return row["values"][field]


def _match_condition(row: dict, cond: dict) -> bool:
    comparison = cond.get("comparison")
    left_prev, left_curr = _operand_value(row, cond.get("left") or {})
    if left_curr is None:
        return False

    if comparison == "is_between":
        try:
            lo = float(cond["low"])
            hi = float(cond["high"])
        except (KeyError, TypeError, ValueError):
            return False
        lo, hi = (lo, hi) if lo <= hi else (hi, lo)
        return lo <= left_curr <= hi

    right_prev, right_curr = _operand_value(row, cond.get("right") or {})
    if right_curr is None:
        return False

    if comparison == "is_above":
        return left_curr > right_curr
    if comparison == "is_below":
        return left_curr < right_curr
    if comparison == "is_at_or_above":
        return left_curr >= right_curr
    if comparison == "is_at_or_below":
        return left_curr <= right_curr
    if comparison in ("crosses_above", "crosses_below"):
        if left_prev is None or right_prev is None:
            return False
        if comparison == "crosses_above":
            return left_prev <= right_prev and left_curr > right_curr
        return left_prev >= right_prev and left_curr < right_curr
    return False


def _describe_condition(cond: dict) -> str:
    left = cond["left"]
    left_label = INDICATORS.get(left.get("field"), left.get("field")) if left.get("type") != "number" else str(left.get("value"))
    comp_label = {
        "crosses_above": "crosses above", "crosses_below": "crosses below",
        "is_above": "is above", "is_below": "is below",
        "is_at_or_above": "is at or above", "is_at_or_below": "is at or below",
        "is_between": "is between",
    }.get(cond.get("comparison"), cond.get("comparison"))
    if cond.get("comparison") == "is_between":
        return f"{left_label} {comp_label} {cond.get('low')} and {cond.get('high')}"
    right = cond.get("right") or {}
    right_label = INDICATORS.get(right.get("field"), right.get("field")) if right.get("type") != "number" else str(right.get("value"))
    return f"{left_label} {comp_label} {right_label}"


def compute_universe(asset_type: str, timeframe: str, max_workers: int = 16) -> list[dict]:
    """The expensive part: fetch OHLCV + compute every indicator for every
    live symbol on one candle timeframe. Meant to be cached per
    (asset_type, timeframe) — see get_delta_indicator_universe() in
    app/api/v1/scanner.py — so trying different condition combinations
    against the same timeframe doesn't re-fetch candles each time."""
    if asset_type not in ASSET_TYPES:
        raise ValueError(f"asset_type must be one of {ASSET_TYPES}")
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"timeframe must be one of {TIMEFRAMES}")

    tickers = _get_tickers(asset_type)
    candidates = [t for t in tickers if t.get("symbol") and float(t.get("close") or 0) > 0]

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_scan_symbol, t, timeframe): t for t in candidates}
        for fut in as_completed(futures):
            r = fut.result()
            if r is not None:
                rows.append(r)
    return rows


def filter_universe(universe: list[dict], conditions: list[dict], combinator: str = "AND") -> dict:
    """Cheap, in-memory filtering against an already-computed universe —
    no network calls, so re-running with different conditions is instant."""
    valid_conditions = [c for c in conditions if c.get("left") and c.get("comparison")]
    combine_any = combinator.upper() == "OR"

    matched = []
    for row in universe:
        if valid_conditions:
            outcomes = [_match_condition(row, c) for c in valid_conditions]
            ok = any(outcomes) if combine_any else all(outcomes)
            if not ok:
                continue
        matched.append({
            "symbol": row["symbol"],
            "description": row["description"],
            "turnover_usd": row["turnover_usd"],
            "price": row["values"]["price"][1],
            "volume_bar": row["values"]["volume_bar"][1],
            "indicators": {k: v[1] for k, v in row["values"].items()},
        })

    matched.sort(key=lambda r: r["turnover_usd"], reverse=True)

    return {
        "generated_at": int(time.time()),
        "universe_size": len(universe),
        "matched": len(matched),
        "conditions_summary": [_describe_condition(c) for c in valid_conditions],
        "indicators": INDICATORS,
        "comparisons": COMPARISONS,
        "results": matched,
    }
