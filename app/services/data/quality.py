"""
Data Quality Engine (Phase 3 of the production-hardening pass).

Investigated first (see docs/IMPROVEMENT_AUDIT.md, Phase 3 section) before
writing anything: this codebase already has real, solid safety nets —
per-provider circuit breakers with Redis-backed cross-process state,
retry-with-backoff, an admin market-pause gate, and a live trading-session
gate. None of them check the *content* of a technically-successful fetch.
A provider can return 200 OK with stale, gapped, duplicated, or
OHLC-inconsistent candles and it sails straight through fetch -> cache ->
signal generation today, with only a bare `len(df) >= 60` row-count check.
This module is that missing check — deliberately a pure, dependency-free
function (no DB, no network, no Flask) so it stays reusable everywhere
a caller has a DataFrame: the signal engine, the backtest engines,
TA Summary, AI Insights, the dashboard, Admin API Configs.

Providers disagree on timestamp timezone-awareness: Delta/Binance return
tz-naive UTC timestamps; Yahoo Finance returns tz-aware timestamps
localized to the instrument's own exchange timezone (confirmed live:
NSE -> Asia/Kolkata, US equities -> America/New_York, forex ->
Europe/London). Comparing a naive and an aware datetime raises
TypeError; comparing two aware datetimes in different zones without
converting first silently miscalculates the gap by the zone offset.
_normalize_utc() below exists specifically so every caller gets a
correct age calculation regardless of which provider the data came from.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

# Bar duration in minutes — mirrors app/services/backtest/runner.py's own
# _TF_MINUTES so "how old is one bar" means the same thing everywhere in
# the codebase. Kept as a separate copy rather than importing that module,
# since this file must have zero dependency on the signal/backtest engines
# to stay usable from every caller listed above without an import cycle.
_TF_MINUTES = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "1d": 1440, "1w": 10080,
}

# How many bar-widths old the last candle can be before it's flagged.
# Deliberately generous: providers commonly lag a bar or two around candle
# close, and a false "stale" verdict silently blocks a real, good signal --
# worse than a slightly lenient threshold. This module has no trading-
# calendar knowledge by design (see module docstring) — a market closed for
# the weekend/a holiday will legitimately show an old last candle; the
# caller (which already has its own session-gate knowledge) decides
# whether "stale" is actually surprising given market hours.
_STALE_AFTER_BARS = 3


def _normalize_utc(ts) -> datetime:
    dt = pd.Timestamp(ts)
    if dt.tzinfo is None:
        return dt.tz_localize("UTC").to_pydatetime()
    return dt.tz_convert("UTC").to_pydatetime()


def assess_data_quality(
    df: pd.DataFrame,
    market: str,
    timeframe: str,
    provider: str | None = None,
) -> dict:
    """Evaluate one OHLCV DataFrame for the checks Phase 3 calls out:
    timestamp age, missing/duplicate candles, invalid OHLC relationships,
    and volume anomalies. Never raises.

    Returns:
        status: "GREEN" | "YELLOW" | "RED"
        issues: list of human-readable findings (empty when GREEN)
        last_candle_age_seconds: float | None
        provider: source provider when known, otherwise None
        market: normalized market identifier supplied by the caller
        timeframe: timeframe supplied by the caller
        candle_count: number of rows assessed
        expected_interval_seconds: expected candle spacing
        last_candle_at: last timestamp normalized to UTC, when available
        warnings: copy of non-fatal issues for consumers that distinguish
            warnings from hard validation failures
        hard_invalid: True if a genuine data-integrity problem was found
            (missing columns, no rows, invalid OHLC, duplicate timestamps,
            negative prices/volume) — this kind of corruption is a bug in
            the data regardless of whether it's live or a historical replay
            and should always block a caller. False when the ONLY findings
            are staleness/gaps/volume-spike, which are only meaningful for
            LIVE generation (a backtest deliberately replays old candles;
            comparing them to "now" would always look stale) — see
            SignalEngine.generate_signal()'s use of this via `force`.
    """
    bar_minutes = _TF_MINUTES.get(timeframe, 60)
    metadata = {
        "provider": provider,
        "market": market,
        "timeframe": timeframe,
        "candle_count": int(len(df)) if df is not None else 0,
        "expected_interval_seconds": bar_minutes * 60,
        "last_candle_at": None,
    }
    if df is None or len(df) == 0:
        return {**metadata, "status": "RED", "issues": ["no data returned"],
                "warnings": [], "last_candle_age_seconds": None, "hard_invalid": True}

    required_cols = {"open", "high", "low", "close"}
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        issue = f"missing required column(s): {sorted(missing_cols)}"
        return {**metadata, "status": "RED", "issues": [issue], "warnings": [],
                "last_candle_age_seconds": None, "hard_invalid": True}

    issues: list[str] = []
    status = "GREEN"
    hard_invalid = False
    # ── Timestamp freshness (soft — see hard_invalid docstring above) ────
    last_ts = _normalize_utc(df.index[-1])
    metadata["last_candle_at"] = last_ts.isoformat()
    age_seconds = (datetime.now(timezone.utc) - last_ts).total_seconds()
    stale_after = bar_minutes * 60 * _STALE_AFTER_BARS
    if age_seconds > stale_after:
        status = "RED"
        issues.append(f"last candle is {age_seconds/60:.0f} min old (expected <= {stale_after/60:.0f} min)")
    elif age_seconds > stale_after * 0.5:
        status = "YELLOW"
        issues.append(f"last candle is {age_seconds/60:.0f} min old (approaching staleness threshold)")

    # ── Duplicate timestamps (hard) ───────────────────────────────────────
    dup_count = int(df.index.duplicated().sum())
    if dup_count:
        status = "RED"
        hard_invalid = True
        issues.append(f"{dup_count} duplicate candle timestamp(s)")

    # ── Missing candles / gaps (soft) ─────────────────────────────────────
    if len(df) > 1:
        deltas = df.index.to_series().diff().dropna()
        expected = pd.Timedelta(minutes=bar_minutes)
        # One missed bar's worth of slack per gap before flagging — minor
        # provider-side jitter is normal and not itself a sign of bad data.
        gap_count = int((deltas > expected * 2).sum())
        if gap_count:
            if status == "GREEN":
                status = "YELLOW"
            issues.append(f"{gap_count} gap(s) larger than 2 bar-widths detected")

    # ── Invalid OHLC relationships (hard) ──────────────────────────────────
    invalid_mask = (
        (df["high"] < df["low"])
        | (df["high"] < df["open"]) | (df["high"] < df["close"])
        | (df["low"] > df["open"]) | (df["low"] > df["close"])
        | (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    )
    invalid_count = int(invalid_mask.sum())
    if invalid_count:
        status = "RED"
        hard_invalid = True
        issues.append(f"{invalid_count} candle(s) with invalid OHLC relationships or non-positive prices")

    # ── Volume anomalies ───────────────────────────────────────────────────
    if "volume" in df.columns and len(df) >= 20:
        vol = df["volume"]
        if (vol < 0).any():
            status = "RED"
            hard_invalid = True
            issues.append("negative volume detected")
        else:
            median_vol = vol.tail(20).median()
            if median_vol > 0 and vol.iloc[-1] > median_vol * 50:
                if status == "GREEN":
                    status = "YELLOW"
                issues.append(f"latest volume is {vol.iloc[-1] / median_vol:.0f}x the recent 20-bar median (possible data glitch)")

    return {
        **metadata,
        "status": status,
        "issues": issues,
        "warnings": list(issues) if not hard_invalid else [
            issue for issue in issues
            if "duplicate" not in issue and "invalid OHLC" not in issue
            and "negative volume" not in issue and "missing required" not in issue
        ],
        "last_candle_age_seconds": round(age_seconds, 1),
        "hard_invalid": hard_invalid,
    }
