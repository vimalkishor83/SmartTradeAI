"""Aggregates for Terminal's frozen live-read lifecycle.

Terminal previews are intentionally not part of Signal/SignalHistory.  Keep
their reporting in one place so every dashboard surface uses the same rules:
open reads are not outcomes, expired reads are visible but not decisive, and
win rate is wins divided by wins plus losses.
"""

from datetime import datetime

from sqlalchemy.orm import joinedload

from app.models.live_read_log import LiveReadLog


_STAGE_LABELS = {
    0: "Before T1",
    1: "After T1",
    2: "After T2",
}


def _number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value


def _round(value, digits=2):
    return round(float(value), digits) if value is not None else None


def _age_minutes(generated_at, now):
    if not generated_at:
        return None
    return max(0, int((now - generated_at).total_seconds() / 60))


def _unrealized_pnl(row):
    entry = _number(row.entry_price)
    current = _number(row.current_price)
    if entry in (None, 0) or current is None:
        return None
    if row.signal_type == "SELL":
        return (entry - current) / entry * 100
    return (current - entry) / entry * 100


def _realized_pnl(row):
    entry = _number(row.entry_price)
    exit_price = _number(row.exit_price)
    if entry in (None, 0) or exit_price is None or row.outcome not in ("win", "loss"):
        return None
    if row.signal_type == "SELL":
        return (entry - exit_price) / entry * 100
    return (exit_price - entry) / entry * 100


def _bucket(rows, key):
    grouped = {}
    for row in rows:
        value = getattr(row, key) or "Unknown"
        grouped.setdefault(str(value), []).append(row)
    return grouped


def _outcome_stats(rows, *, now):
    wins = sum(row.outcome == "win" for row in rows)
    losses = sum(row.outcome == "loss" for row in rows)
    expired = sum(row.outcome == "expired" for row in rows)
    decisive = wins + losses
    realized = [_realized_pnl(row) for row in rows]
    realized = [value for value in realized if value is not None]
    return {
        "total": len(rows),
        "resolved": len(rows),
        "decisive": decisive,
        "wins": wins,
        "losses": losses,
        "expired": expired,
        "win_rate": _round(wins / decisive * 100, 1) if decisive else None,
        "net_pnl_pct": _round(sum(realized)) if realized else 0.0,
        "avg_pnl_pct": _round(sum(realized) / len(realized), 3) if realized else None,
    }


def _open_stats(rows, *, now):
    pnl_values = [_unrealized_pnl(row) for row in rows]
    pnl_values = [value for value in pnl_values if value is not None]
    ages = [_age_minutes(row.generated_at, now) for row in rows]
    ages = [value for value in ages if value is not None]
    stages = {}
    for row in rows:
        stage = max(0, min(2, int(row.trail_stage or 0)))
        stages[stage] = stages.get(stage, 0) + 1
    return {
        "count": len(rows),
        "buy": sum(row.signal_type == "BUY" for row in rows),
        "sell": sum(row.signal_type == "SELL" for row in rows),
        "with_live_price": len(pnl_values),
        "avg_unrealized_pnl_pct": _round(sum(pnl_values) / len(pnl_values), 3) if pnl_values else None,
        "best_unrealized_pnl_pct": _round(max(pnl_values)) if pnl_values else None,
        "worst_unrealized_pnl_pct": _round(min(pnl_values)) if pnl_values else None,
        "positive_pnl": sum(value > 0 for value in pnl_values),
        "negative_pnl": sum(value < 0 for value in pnl_values),
        "avg_age_minutes": _round(sum(ages) / len(ages), 1) if ages else None,
        "oldest_age_minutes": max(ages) if ages else None,
        "by_stage": [
            {"stage": stage, "label": _STAGE_LABELS[stage], "count": stages.get(stage, 0)}
            for stage in range(3)
            if stages.get(stage, 0)
        ],
    }


def _group_row(rows, name, *, now):
    open_rows = [row for row in rows if row.outcome is None]
    closed_rows = [row for row in rows if row.outcome is not None]
    decisive_rows = [row for row in closed_rows if row.outcome in ("win", "loss")]
    open_stats = _open_stats(open_rows, now=now)
    closed_stats = _outcome_stats(closed_rows, now=now)
    return {
        "name": name,
        "total": len(rows),
        "open": len(open_rows),
        "resolved": len(closed_rows),
        "decisive": len(decisive_rows),
        "wins": closed_stats["wins"],
        "losses": closed_stats["losses"],
        "expired": closed_stats["expired"],
        "win_rate": closed_stats["win_rate"],
        "open_avg_unrealized_pnl_pct": open_stats["avg_unrealized_pnl_pct"],
        "open_avg_age_minutes": open_stats["avg_age_minutes"],
    }


def build_live_read_performance(start_at=None, end_at=None):
    """Return a source-separated Terminal performance snapshot.

    When a date range is supplied, only resolved rows whose ``resolved_at``
    falls inside it are included in the closed section.  Current open rows
    remain visible regardless of the historical range because they are a
    present-state operational metric, not historical outcomes.
    """
    query = LiveReadLog.query.options(joinedload(LiveReadLog.asset))
    rows = query.order_by(LiveReadLog.generated_at.asc(), LiveReadLog.id.asc()).all()
    if start_at is not None:
        rows = [row for row in rows if row.outcome is None or (row.resolved_at and row.resolved_at >= start_at)]
    if end_at is not None:
        rows = [row for row in rows if row.outcome is None or (row.resolved_at and row.resolved_at < end_at)]

    now = datetime.utcnow()
    open_rows = [row for row in rows if row.outcome is None]
    closed_rows = [row for row in rows if row.outcome is not None]
    closed = _outcome_stats(closed_rows, now=now)
    open_stats = _open_stats(open_rows, now=now)

    by_timeframe = [
        _group_row(group, timeframe, now=now)
        for timeframe, group in sorted(_bucket(rows, "timeframe").items())
    ]
    by_asset = [
        {
            **_group_row(group, row.asset.symbol if row.asset else "Unknown", now=now),
            "asset_id": row.asset_id,
        }
        for row, group in sorted(
            ((group[0], group) for group in _bucket(rows, "asset_id").values()),
            key=lambda item: (-len(item[1]), str(item[0].asset.symbol if item[0].asset else "Unknown")),
        )
    ]

    return {
        "source": "terminal",
        "source_label": "Terminal live reads",
        "total_logged": len(rows),
        "resolved": len(closed_rows),
        "decisive": closed["decisive"],
        "expired": closed["expired"],
        "open": len(open_rows),
        "win_rate": closed["win_rate"],
        "closed": closed,
        "open_stats": open_stats,
        "by_timeframe": by_timeframe,
        "by_asset": by_asset[:50],
    }
