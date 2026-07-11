"""
SignalHistory analyzer.

Reports proven statistics from real closed signals already in the database,
and runs "what-if" analysis showing how the numbers change under different
win-rate definitions. This proves the *current live reality* (as opposed to
runner.py, which re-simulates on historical candles for tuning).

Key insight surfaced here: the live dashboard win rate is
    wins / total
where `total` includes `neutral` (expired) signals that never reached a
target or stop. Excluding those undecided trades gives the true directional
accuracy, which is almost always meaningfully higher.
"""
from __future__ import annotations

from sqlalchemy import func

from app.extensions import db
from app.models.signal import SignalHistory
from app.models.asset import Asset


def _rate(wins: int, total: int) -> float:
    return round(wins / total * 100, 1) if total else 0.0


def _block(rows) -> dict:
    """Compute a stats block from an iterable of SignalHistory rows."""
    wins = sum(1 for r in rows if r.outcome == "win")
    losses = sum(1 for r in rows if r.outcome == "loss")
    neutral = sum(1 for r in rows if r.outcome not in ("win", "loss"))
    total = wins + losses + neutral
    decided = wins + losses

    pnls = [r.pnl_pct for r in rows if r.pnl_pct is not None]
    avg_pnl = round(sum(pnls) / len(pnls), 2) if pnls else 0.0
    gross_win = sum(r.pnl_pct for r in rows if r.outcome == "win" and r.pnl_pct)
    gross_loss = abs(sum(r.pnl_pct for r in rows if r.outcome == "loss" and r.pnl_pct))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss else (round(gross_win, 2) if gross_win else 0.0)

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "neutral": neutral,
        "raw_win_rate": _rate(wins, total),        # matches live dashboard (incl. neutral)
        "true_win_rate": _rate(wins, decided),     # wins / (wins + losses)
        "avg_pnl_pct": avg_pnl,
        "profit_factor": profit_factor,
    }


def analyze_history(rows=None) -> dict:
    """
    Full breakdown of real closed signals: overall, per timeframe, per market,
    and per signal type — each with both raw and true win rates.

    `rows` may be passed in by the caller (a pre-fetched SignalHistory list)
    to share one query with whatif_expiry() — history-stats calls both
    together on every request, and each independently ran its own unbounded
    SignalHistory.query.all() (3 full-table loads total across the two
    functions for one HTTP request) before this was threaded through.
    """
    if rows is None:
        rows = SignalHistory.query.all()

    overall = _block(rows)

    # Per timeframe
    tfs = sorted({r.timeframe for r in rows if r.timeframe})
    by_timeframe = [{"timeframe": tf, **_block([r for r in rows if r.timeframe == tf])} for tf in tfs]

    # Per signal type
    sts = sorted({r.signal_type for r in rows if r.signal_type})
    by_signal_type = [{"signal_type": st, **_block([r for r in rows if r.signal_type == st])} for st in sts]

    # Per market — needs the asset join; build an asset_id -> market map once.
    market_map = dict(db.session.query(Asset.id, Asset.market).all())
    markets: dict[str, list] = {}
    for r in rows:
        mkt = market_map.get(r.asset_id, "unknown")
        markets.setdefault(mkt, []).append(r)
    by_market = [{"market": mkt, **_block(rs)} for mkt, rs in markets.items()]

    # Confidence buckets — does higher confidence actually win more?
    buckets = []
    for lo, hi, label in [(50, 60, "50-60%"), (60, 70, "60-70%"), (70, 80, "70-80%"),
                          (80, 90, "80-90%"), (90, 101, "90-100%")]:
        seg = [r for r in rows if r.confidence_score is not None and lo <= r.confidence_score < hi]
        buckets.append({"range": label, **_block(seg)})

    return {
        "overall": overall,
        "by_timeframe": sorted(by_timeframe, key=lambda x: x["true_win_rate"], reverse=True),
        "by_market": sorted(by_market, key=lambda x: x["true_win_rate"], reverse=True),
        "by_signal_type": by_signal_type,
        "by_confidence": buckets,
        "note": (
            "raw_win_rate matches the dashboard (neutral/expired counted as non-wins). "
            "true_win_rate = wins / (wins + losses), excluding undecided trades."
        ),
    }


def whatif_expiry(rows=None) -> dict:
    """
    'What-if' analysis: of the signals that expired NEUTRAL, how many were
    moving in the RIGHT direction at close (pnl_pct > 0) vs the wrong one?

    A large share of neutral-but-positive trades is strong evidence that the
    expiry window is too short — the target simply wasn't given enough time.
    This is the primary diagnostic for the expiry/R:R fix.

    `rows` may be passed in (see analyze_history's docstring) to avoid this
    function's own two separate unbounded SignalHistory.query.all() calls.
    """
    if rows is None:
        rows = SignalHistory.query.all()

    neutral = [r for r in rows if r.outcome not in ("win", "loss")]

    total = len(neutral)
    right_dir = sum(1 for r in neutral if (r.pnl_pct or 0) > 0)
    wrong_dir = sum(1 for r in neutral if (r.pnl_pct or 0) < 0)
    flat = total - right_dir - wrong_dir

    # If we treated "expired but in-profit" as partial wins, what would the
    # overall win rate become? (Illustrative upper bound, not a promise.)
    all_rows = rows
    wins = sum(1 for r in all_rows if r.outcome == "win")
    grand_total = len(all_rows)

    current_raw = _rate(wins, grand_total)
    with_partial = _rate(wins + right_dir, grand_total)

    return {
        "neutral_signals": total,
        "moving_right_direction": right_dir,
        "moving_wrong_direction": wrong_dir,
        "flat": flat,
        "pct_neutral_in_profit": _rate(right_dir, total),
        "current_raw_win_rate": current_raw,
        "win_rate_if_neutral_profit_counted": with_partial,
        "interpretation": (
            "If a high share of neutral signals were moving in the right direction, "
            "the expiry window is too short and/or targets are too far — lengthening "
            "expiry should convert many of these into wins."
        ),
    }
