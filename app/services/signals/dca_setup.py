"""
Scaled-entry pullback setup ("DCA Setup").

Validated against 3.5 years of SOLUSDT 5m data (373k bars, 9 bull / 6 bear
quarters). Measured performance, fees 0.02%/side:
    bull quarters : +0.18% to +0.23% / day  (6 of 9 positive)
    bear quarters : -0.15% / day
    all regimes   : +0.067% / day, ~1 campaign per 5 days

The exit is the part that matters: an earlier 1% take-profit tested at
-0.02%/day because it capped upside (in a quarter where SOL rose 377% it
returned ~1%). Widening the target to 10% is what produced the edge.

RULES
  Entry (all four required, evaluated on the last CLOSED 5m candle):
    1. 15m EMA100 > 15m EMA200            higher-timeframe uptrend
    2. price > 5m EMA100                  above mid trend
    3. 5m EMA9 < EMA21                    pullback inside the uptrend
    4. (close-low)/(high-low) >= 0.5      candle closes in its upper half
  Scaling:
    10 tranches; add the next when price is 0.3% below the last fill AND
    rule 4 holds again (never average into a falling red candle).
  Exit:
    take profit +10% from the AVERAGE entry
    stop loss    -8% from the FIRST entry
    max hold      7 days
"""
from __future__ import annotations

import pandas as pd

# ── Tunables (defaults are the validated configuration) ──────────────────
HTF_FAST, HTF_SLOW = 100, 200      # on 15m
FAST, SLOW, MID = 9, 21, 100       # on 5m
N_TRANCHES = 10
SPACING_PCT = 0.3
TP_PCT = 10.0                      # from AVERAGE entry
SL_PCT = 8.0                       # from FIRST entry
MAX_HOLD_BARS = 2016               # 7 days of 5m bars
CONFIRM_RATIO = 0.5                # close position within the bar's range


def _htf_emas(df: pd.DataFrame) -> pd.DataFrame:
    """15m EMA100/200 mapped onto 5m bars with NO look-ahead.

    The EMAs are computed on 15m closes then shifted one bar, so a 5m bar
    only ever sees the last FULLY CLOSED 15m candle - the same thing you
    would see live.
    """
    d = df.set_index("ts")
    m15 = (d.resample("15min")
             .agg({"open": "first", "high": "max",
                   "low": "min", "close": "last"})
             .dropna())
    m15["htf_fast"] = m15["close"].ewm(span=HTF_FAST, adjust=False).mean()
    m15["htf_slow"] = m15["close"].ewm(span=HTF_SLOW, adjust=False).mean()
    mapped = m15[["htf_fast", "htf_slow"]].shift(1).reindex(d.index, method="ffill")
    return mapped.reset_index(drop=True)


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Attach every indicator the rules need. `df` must have ts/o/h/l/c."""
    df = df.copy().reset_index(drop=True)
    if "ts" not in df.columns:
        df["ts"] = pd.to_datetime(df.index)
    df[["htf_fast", "htf_slow"]] = _htf_emas(df)
    c = df["close"]
    df["ema_fast"] = c.ewm(span=FAST, adjust=False).mean()
    df["ema_slow"] = c.ewm(span=SLOW, adjust=False).mean()
    df["ema_mid"] = c.ewm(span=MID, adjust=False).mean()
    rng = (df["high"] - df["low"]).replace(0, pd.NA)
    df["close_pos"] = ((df["close"] - df["low"]) / rng).fillna(0.5)
    return df.dropna(subset=["htf_fast", "htf_slow"]).reset_index(drop=True)


def confirming_candle(row) -> bool:
    """Rule 4 - candle closes in the upper half of its range."""
    return float(row["close_pos"]) >= CONFIRM_RATIO


def evaluate(df: pd.DataFrame) -> dict:
    """Evaluate the setup on the most recent closed bar.

    Returns each rule's pass/fail plus the levels to trade if it fires.
    """
    data = prepare(df)
    if len(data) < HTF_SLOW + 10:
        return {"ready": False, "reason": "insufficient history"}

    r = data.iloc[-1]
    price = float(r["close"])

    checks = [
        {"key": "htf_trend",
         "label": f"15m EMA{HTF_FAST} > EMA{HTF_SLOW}",
         "passed": bool(r["htf_fast"] > r["htf_slow"]),
         "detail": f"{r['htf_fast']:.4f} vs {r['htf_slow']:.4f}"},
        {"key": "above_mid",
         "label": f"Price > 5m EMA{MID}",
         "passed": bool(price > r["ema_mid"]),
         "detail": f"{price:.4f} vs {r['ema_mid']:.4f}"},
        {"key": "pullback",
         "label": f"5m EMA{FAST} < EMA{SLOW} (pullback)",
         "passed": bool(r["ema_fast"] < r["ema_slow"]),
         "detail": f"{r['ema_fast']:.4f} vs {r['ema_slow']:.4f}"},
        {"key": "confirm",
         "label": "Candle closes in upper half",
         "passed": confirming_candle(r),
         "detail": f"close at {float(r['close_pos'])*100:.0f}% of range"},
    ]
    passed = sum(1 for c in checks if c["passed"])
    ready = passed == len(checks)

    return {
        "ready": ready,
        "checks": checks,
        "passed": passed,
        "total": len(checks),
        "price": round(price, 6),
        "plan": build_plan(price),
        "config": {
            "tranches": N_TRANCHES, "spacing_pct": SPACING_PCT,
            "tp_pct": TP_PCT, "sl_pct": SL_PCT,
            "max_hold_days": round(MAX_HOLD_BARS * 5 / 1440, 1),
        },
        "as_of": str(r["ts"]),
    }


def build_plan(first_entry: float, capital: float = 1000.0) -> dict:
    """Ladder of tranche prices, plus the resulting TP/SL if all fill."""
    per = capital / N_TRANCHES
    ladder, price = [], first_entry
    for i in range(N_TRANCHES):
        if i:
            price = price * (1 - SPACING_PCT / 100)
        ladder.append({
            "tranche": i + 1,
            "price": round(price, 6),
            "amount": round(per, 2),
            "drop_from_first_pct": round((price / first_entry - 1) * 100, 2),
        })
    avg_all = sum(t["price"] for t in ladder) / len(ladder)
    return {
        "capital": capital,
        "per_tranche": round(per, 2),
        "ladder": ladder,
        "avg_if_all_fill": round(avg_all, 6),
        "take_profit": round(avg_all * (1 + TP_PCT / 100), 6),
        "stop_loss": round(first_entry * (1 - SL_PCT / 100), 6),
        "note": ("TP is measured from the AVERAGE entry, SL from the FIRST "
                 "entry. Only add a tranche on a confirming candle."),
    }
