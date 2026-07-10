"""
EMA 9/21 multi-timeframe confirmation logic.

Core idea: on a "base" timeframe, trend direction is read from the EMA9/EMA21
relationship (fast above slow = bullish structure, fast below slow = bearish),
confirmed by price itself trading back on the correct side of the fast EMA
(filters out a bare EMA cross the price hasn't followed through on yet).
That base-timeframe read is then checked against the same EMA9/21 read on the
next-higher timeframe in the sequence — agreement between the two timeframes
is what earns a "Strong" rating; disagreement is reported as Neutral rather
than picked one way or the other, so the table never overstates conviction.

Higher-timeframe pairing (each base timeframe confirmed by the next one up):
    5m -> 15m -> 30m -> 1h -> 2h -> 4h -> 1d (no higher pair available)

This mirrors the "higher-timeframe gate" idea already used for signal
generation elsewhere in the app, applied here specifically to the EMA9/21
cross so every cell states exactly which two numbers on which two timeframes
produced it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from app.services.indicators.calculator import calculate_ema

# Ordered timeframe ladder used everywhere in the app for the TA Summary grid.
TA_TIMEFRAMES = ["5m", "15m", "30m", "1h", "2h", "4h", "1d"]

#: base timeframe -> its confirming higher timeframe (None = no higher pair).
HIGHER_TF_MAP: dict[str, str | None] = {
    tf: (TA_TIMEFRAMES[i + 1] if i + 1 < len(TA_TIMEFRAMES) else None)
    for i, tf in enumerate(TA_TIMEFRAMES)
}

#: Minimum candles needed for a stable EMA21 read (a few periods of warm-up
#: beyond the span itself so the EMA has settled rather than reading the
#: very first few bars where ewm() is still converging).
MIN_BARS = 25

# Bias requires the fast/slow EMAs to be separated by more than this fraction
# of the slow EMA — filters out noise right at a crossover from flipping the
# label back and forth every bar.
_NOISE_THRESHOLD_PCT = 0.0005  # 0.05%

_SCORE_BY_RATING = {
    "Strong Buy": 1.0,
    "Buy": 0.5,
    "Neutral": 0.0,
    "Sell": -0.5,
    "Strong Sell": -1.0,
}


@dataclass(frozen=True)
class TfEmaRead:
    """EMA9/21 read for a single timeframe."""

    timeframe: str
    ema9: float | None
    ema21: float | None
    close: float | None
    bias: str  # "bullish" | "bearish" | "neutral" | "unavailable"
    timestamp: str | None = None  # ISO timestamp of the bar this read is "as of"

    def to_dict(self) -> dict:
        return {
            "timeframe": self.timeframe,
            "ema9": self.ema9,
            "ema21": self.ema21,
            "close": self.close,
            "bias": self.bias,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class Ema921Cell:
    """One table cell: the combined base + higher-timeframe verdict."""

    rating: str  # Strong Buy / Buy / Neutral / Sell / Strong Sell
    score: float  # -1..1, same convention as the existing TA rating score
    conflicting: bool
    base: TfEmaRead
    higher: TfEmaRead | None
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "rating": self.rating,
            "score": self.score,
            "conflicting": self.conflicting,
            "base": self.base.to_dict(),
            "higher": self.higher.to_dict() if self.higher else None,
            "reason": self.reason,
        }


def read_ema921(df: pd.DataFrame | None, timeframe: str, bars_back: int = 0) -> TfEmaRead:
    """Compute the EMA9/21 bias for one timeframe's OHLCV data.

    ``bars_back=0`` (default) reads the latest closed bar — live behaviour,
    unchanged from before. ``bars_back=N`` reads as of N bars before the
    latest one, computing the EMAs only from bars up to and including that
    point (the tail is never sliced off first, since `.ewm()` needs the whole
    warm-up run to converge — instead we simply stop *reading* N bars early;
    the bars beyond that point are never touched, so no future information
    can leak into the read).
    """
    if df is None or len(df) < MIN_BARS + bars_back:
        return TfEmaRead(timeframe, None, None, None, "unavailable")

    pos = len(df) - 1 - bars_back
    close = df["close"].iloc[: pos + 1]
    ema9 = float(calculate_ema(close, 9).iloc[-1])
    ema21 = float(calculate_ema(close, 21).iloc[-1])
    last_close = float(close.iloc[-1])
    ts = df.index[pos]
    ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

    if any(pd.isna(v) for v in (ema9, ema21, last_close)):
        return TfEmaRead(timeframe, None, None, None, "unavailable", ts_iso)

    threshold = abs(ema21) * _NOISE_THRESHOLD_PCT
    if ema9 > ema21 + threshold and last_close >= ema9:
        bias = "bullish"
    elif ema9 < ema21 - threshold and last_close <= ema9:
        bias = "bearish"
    else:
        bias = "neutral"

    return TfEmaRead(timeframe, round(ema9, 6), round(ema21, 6), round(last_close, 6), bias, ts_iso)


def _as_of_bars_back(higher_df: pd.DataFrame | None, as_of_ts) -> int | None:
    """How many bars back into ``higher_df`` to land on the latest bar whose
    timestamp is <= ``as_of_ts`` (a point-in-time "as-of" join). Returns None
    if there is no such bar (as_of_ts is before the series even starts)."""
    if higher_df is None or as_of_ts is None or len(higher_df) == 0:
        return None
    pos = higher_df.index.searchsorted(as_of_ts, side="right") - 1
    if pos < 0:
        return None
    return (len(higher_df) - 1) - int(pos)


def combine_ema921(base: TfEmaRead, higher: TfEmaRead | None) -> Ema921Cell:
    """Combine a base-timeframe read with its higher-timeframe confirmation."""
    if base.bias == "unavailable":
        return Ema921Cell("Neutral", 0.0, False, base, higher, "Not enough data yet.")

    higher_bias = higher.bias if higher and higher.bias != "unavailable" else None
    conflicting = bool(
        higher_bias and (
            (base.bias == "bullish" and higher_bias == "bearish")
            or (base.bias == "bearish" and higher_bias == "bullish")
        )
    )

    if base.bias == "neutral":
        rating = "Neutral"
    elif conflicting:
        rating = "Neutral"
    elif base.bias == "bullish" and higher_bias == "bullish":
        rating = "Strong Buy"
    elif base.bias == "bullish":
        rating = "Buy"
    elif base.bias == "bearish" and higher_bias == "bearish":
        rating = "Strong Sell"
    else:  # base.bias == "bearish"
        rating = "Sell"

    reason = _explain(base, higher, rating, conflicting)
    return Ema921Cell(rating, _SCORE_BY_RATING[rating], conflicting, base, higher, reason)


def _explain(base: TfEmaRead, higher: TfEmaRead | None, rating: str, conflicting: bool) -> str:
    def fmt(read: TfEmaRead) -> str:
        if read.bias == "unavailable":
            return f"{read.timeframe}: not enough data"
        rel = ">" if read.ema9 >= read.ema21 else "<"
        return (f"{read.timeframe}: EMA9={read.ema9} {rel} EMA21={read.ema21}, "
                f"price={read.close} -> {read.bias}")

    parts = [fmt(base)]
    if higher is not None:
        parts.append(fmt(higher))
    else:
        parts.append("no higher timeframe available for this column")

    if conflicting:
        parts.append("timeframes disagree -> reported as Neutral rather than guessing")
    return " | ".join(parts) + f" => {rating}"


def compute_ema921_cell(
    base_df: pd.DataFrame | None, base_tf: str, higher_df: pd.DataFrame | None,
    bars_back: int = 0,
) -> Ema921Cell:
    """One-call convenience: read both timeframes and combine them.

    ``bars_back`` steps the *base* timeframe back N of its own bars (live
    behaviour at 0). The higher timeframe is then aligned by an as-of join on
    the base bar's own timestamp — so scrubbing the 5m column back 25 minutes
    correctly reads the 15m EMA as it stood at that moment, never a 15m bar
    that closes later (which would be look-ahead, the exact bug class this
    whole app's backtesting work has been careful to avoid elsewhere).
    """
    higher_tf = HIGHER_TF_MAP.get(base_tf)
    base_read = read_ema921(base_df, base_tf, bars_back)

    higher_read = None
    if higher_tf and higher_df is not None and base_read.bias != "unavailable":
        base_ts = base_df.index[len(base_df) - 1 - bars_back]
        higher_bars_back = _as_of_bars_back(higher_df, base_ts)
        if higher_bars_back is not None:
            higher_read = read_ema921(higher_df, higher_tf, higher_bars_back)

    return combine_ema921(base_read, higher_read)
