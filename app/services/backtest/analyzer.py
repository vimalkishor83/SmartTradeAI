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

from sqlalchemy import and_, case, func, or_

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


def _stat_expressions():
    """Return reusable SQL aggregates for the public stats-block contract."""
    return (
        func.count(SignalHistory.id).label("total"),
        func.coalesce(func.sum(case((SignalHistory.outcome == "win", 1), else_=0)), 0).label("wins"),
        func.coalesce(func.sum(case((SignalHistory.outcome == "loss", 1), else_=0)), 0).label("losses"),
        func.coalesce(
            func.sum(case((SignalHistory.outcome.in_(("win", "loss")), 0), else_=1)),
            0,
        ).label("neutral"),
        func.avg(SignalHistory.pnl_pct).label("avg_pnl"),
        func.coalesce(
            func.sum(case((SignalHistory.outcome == "win", SignalHistory.pnl_pct), else_=0)),
            0,
        ).label("gross_win"),
        func.coalesce(
            func.sum(case((SignalHistory.outcome == "loss", SignalHistory.pnl_pct), else_=0)),
            0,
        ).label("gross_loss"),
    )


def _stats_from_row(row) -> dict:
    """Convert one SQL aggregate row to the established stats-block shape."""
    wins = int(row.wins or 0)
    losses = int(row.losses or 0)
    neutral = int(row.neutral or 0)
    total = int(row.total or 0)
    decided = wins + losses
    avg_pnl = round(float(row.avg_pnl), 2) if row.avg_pnl is not None else 0.0
    gross_win = float(row.gross_win or 0)
    gross_loss = abs(float(row.gross_loss or 0))
    profit_factor = (
        round(gross_win / gross_loss, 2)
        if gross_loss
        else (round(gross_win, 2) if gross_win else 0.0)
    )
    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "neutral": neutral,
        "raw_win_rate": _rate(wins, total),
        "true_win_rate": _rate(wins, decided),
        "avg_pnl_pct": avg_pnl,
        "profit_factor": profit_factor,
    }


def _empty_stats() -> dict:
    """Return the zero-state used for confidence buckets with no rows."""
    return {
        "total": 0,
        "wins": 0,
        "losses": 0,
        "neutral": 0,
        "raw_win_rate": 0.0,
        "true_win_rate": 0.0,
        "avg_pnl_pct": 0.0,
        "profit_factor": 0.0,
    }


def _grouped_stats(group_expr, *, filter_expr=None, join_asset=False):
    query = db.session.query(
        group_expr.label("bucket"),
        *_stat_expressions(),
    ).select_from(SignalHistory)
    if join_asset:
        query = query.outerjoin(Asset, Asset.id == SignalHistory.asset_id)
    if filter_expr is not None:
        query = query.filter(filter_expr)
    return query.group_by(group_expr).all()


def _analyze_history_sql() -> dict:
    """Build history analytics in PostgreSQL/SQLite without loading rows."""
    overall_row = db.session.query(*_stat_expressions()).select_from(SignalHistory).one()
    overall = _stats_from_row(overall_row)

    timeframe_rows = _grouped_stats(
        SignalHistory.timeframe,
        filter_expr=and_(
            SignalHistory.timeframe.isnot(None),
            SignalHistory.timeframe != "",
        ),
    )
    by_timeframe = [
        {"timeframe": row.bucket, **_stats_from_row(row)}
        for row in timeframe_rows
    ]

    signal_type_rows = _grouped_stats(
        SignalHistory.signal_type,
        filter_expr=and_(
            SignalHistory.signal_type.isnot(None),
            SignalHistory.signal_type != "",
        ),
    )
    by_signal_type = [
        {"signal_type": row.bucket, **_stats_from_row(row)}
        for row in signal_type_rows
    ]

    market_expr = func.coalesce(Asset.market, "unknown")
    market_rows = _grouped_stats(market_expr, join_asset=True)
    by_market = [
        {"market": row.bucket, **_stats_from_row(row)}
        for row in market_rows
    ]

    confidence_expr = case(
        (and_(SignalHistory.confidence_score >= 50, SignalHistory.confidence_score < 60), "50-60%"),
        (and_(SignalHistory.confidence_score >= 60, SignalHistory.confidence_score < 70), "60-70%"),
        (and_(SignalHistory.confidence_score >= 70, SignalHistory.confidence_score < 80), "70-80%"),
        (and_(SignalHistory.confidence_score >= 80, SignalHistory.confidence_score < 90), "80-90%"),
        (and_(SignalHistory.confidence_score >= 90, SignalHistory.confidence_score < 101), "90-100%"),
        else_=None,
    )
    confidence_rows = {
        row.bucket: _stats_from_row(row)
        for row in _grouped_stats(
            confidence_expr,
            filter_expr=confidence_expr.isnot(None),
        )
    }
    confidence_ranges = ["50-60%", "60-70%", "70-80%", "80-90%", "90-100%"]
    by_confidence = [
        {"range": label, **confidence_rows.get(label, _empty_stats())}
        for label in confidence_ranges
    ]

    return {
        "overall": overall,
        "by_timeframe": sorted(by_timeframe, key=lambda x: x["true_win_rate"], reverse=True),
        "by_market": sorted(by_market, key=lambda x: x["true_win_rate"], reverse=True),
        "by_signal_type": by_signal_type,
        "by_confidence": by_confidence,
        "note": (
            "raw_win_rate matches the dashboard (neutral/expired counted as non-wins). "
            "true_win_rate = wins / (wins + losses), excluding undecided trades."
        ),
    }


def analyze_history(rows=None) -> dict:
    """
    Full breakdown of real closed signals: overall, per timeframe, per market,
    and per signal type — each with both raw and true win rates.

    `rows` may be passed in by callers that already have a history list. When
    omitted, the default path uses database-side aggregates so history size
    does not become Python memory usage.
    """
    if rows is None:
        return _analyze_history_sql()

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

    `rows` may be passed in (see analyze_history's docstring) for callers that
    already have a history list; the default path uses database aggregates.
    """
    if rows is None:
        return _whatif_expiry_sql()

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


def _whatif_expiry_sql() -> dict:
    """Run expiry diagnostics with conditional SQL aggregates."""
    neutral_filter = or_(
        SignalHistory.outcome.notin_(("win", "loss")),
        SignalHistory.outcome.is_(None),
    )
    row = db.session.query(
        func.coalesce(func.sum(case((neutral_filter, 1), else_=0)), 0).label("neutral_signals"),
        func.coalesce(
            func.sum(case((and_(neutral_filter, SignalHistory.pnl_pct > 0), 1), else_=0)),
            0,
        ).label("moving_right"),
        func.coalesce(
            func.sum(case((and_(neutral_filter, SignalHistory.pnl_pct < 0), 1), else_=0)),
            0,
        ).label("moving_wrong"),
        func.coalesce(func.sum(case((SignalHistory.outcome == "win", 1), else_=0)), 0).label("wins"),
        func.count(SignalHistory.id).label("grand_total"),
    ).select_from(SignalHistory).one()

    total = int(row.neutral_signals or 0)
    right_dir = int(row.moving_right or 0)
    wrong_dir = int(row.moving_wrong or 0)
    flat = total - right_dir - wrong_dir
    wins = int(row.wins or 0)
    grand_total = int(row.grand_total or 0)

    return {
        "neutral_signals": total,
        "moving_right_direction": right_dir,
        "moving_wrong_direction": wrong_dir,
        "flat": flat,
        "pct_neutral_in_profit": _rate(right_dir, total),
        "current_raw_win_rate": _rate(wins, grand_total),
        "win_rate_if_neutral_profit_counted": _rate(wins + right_dir, grand_total),
        "interpretation": (
            "If a high share of neutral signals were moving in the right direction, "
            "the expiry window is too short and/or targets are too far — lengthening "
            "expiry should convert many of these into wins."
        ),
    }
