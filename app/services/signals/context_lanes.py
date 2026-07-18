"""
Narrative and Macro lane verdicts — the two Deeepr-style context lanes that
need DB-backed news/economic-calendar data.

Kept out of engine.py deliberately: SignalEngine.generate_signal() is called
candle-by-candle during walk-forward backtests (app/services/backtest/runner.py)
with no Flask app/DB context guarantee in that inner loop. Mixing DB queries
into the engine would run a query per historical candle and could silently
change backtest results. These lanes are purely additive context computed
once per live/auto-generate signal, not part of the direction/entry/stop/
target math.
"""
from __future__ import annotations

from datetime import datetime, timedelta


def _verdict_from_pct(pct: float) -> str:
    if pct >= 0.6:
        return "HIGH"
    if pct >= 0.3:
        return "MODERATE"
    return "LOW"


def fetch_context_data(lookback_hours: int = 48, event_horizon_hours: int = 24) -> dict:
    """Fetch News + EconomicEvent rows ONCE per generation cycle so the
    per-asset lane functions below can filter them in-memory instead of each
    issuing their own DB query (auto-generate runs these across many
    asset x timeframe combos per cycle)."""
    from app.models.news import News
    from app.models.economic import EconomicEvent

    news_cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
    news_items = News.query.filter(News.published_at >= news_cutoff).all()

    now = datetime.utcnow()
    window_end = now + timedelta(hours=event_horizon_hours)
    econ_events = EconomicEvent.query.filter(
        EconomicEvent.event_time.between(now, window_end)
    ).all()

    return {"news_items": news_items, "econ_events": econ_events}


def narrative_lane(asset, direction: str, news_items: list) -> dict:
    """Bullish/bearish tilt of recent news coverage for this asset, from the
    Yahoo RSS-derived News table (services/news/fetcher.py, refreshed every
    30min)."""
    relevant = [n for n in news_items if n.related_assets and asset.symbol in n.related_assets]

    if not relevant:
        return {
            "score": 50, "verdict": "LOW",
            "reasons": ["No recent news coverage"],
            "direction": "neutral", "article_count": 0,
        }

    avg = sum((n.sentiment_score or 0) for n in relevant) / len(relevant)
    lane_dir = "bullish" if avg > 0.1 else "bearish" if avg < -0.1 else "neutral"
    agrees = (lane_dir == "bullish" and direction == "BUY") or (lane_dir == "bearish" and direction == "SELL")

    pct = min(1.0, abs(avg)) if agrees else max(0.0, 0.5 - abs(avg))

    top = sorted(relevant, key=lambda n: n.published_at or datetime.min, reverse=True)[:2]
    reasons = [n.title for n in top] or ["No standout headlines"]

    return {
        "score": round(pct * 100), "verdict": _verdict_from_pct(pct),
        "reasons": reasons, "direction": lane_dir, "article_count": len(relevant),
    }


def macro_lane(asset, direction: str, higher_tf_bias: str | None, econ_events: list) -> dict:
    """Macro-trend agreement (higher-timeframe bias) + upcoming high-impact
    economic-calendar event risk for this asset's currencies."""
    relevant_ccys = {"USD"}  # USD macro prints move every market, crypto included
    if getattr(asset, "base_currency", None):
        relevant_ccys.add(asset.base_currency)
    if getattr(asset, "quote_currency", None):
        relevant_ccys.add(asset.quote_currency)

    high_impact = [e for e in econ_events if e.impact == "high" and e.currency in relevant_ccys]

    mtf_agrees = (higher_tf_bias == "bullish" and direction == "BUY") or \
                 (higher_tf_bias == "bearish" and direction == "SELL")

    reasons = []
    if higher_tf_bias and higher_tf_bias != "neutral":
        pct = 0.7 if mtf_agrees else 0.3
        reasons.append(f"Higher-timeframe trend is {higher_tf_bias}" +
                        (" (aligned)" if mtf_agrees else " (conflicting)"))
    else:
        pct = 0.5
        reasons.append("No clear higher-timeframe bias")

    if high_impact:
        pct = max(0.0, pct - 0.15)  # event risk trims the verdict regardless of direction
        names = ", ".join(e.title for e in high_impact[:2])
        reasons.append(f"High-impact event(s) in next 24h: {names}")
    else:
        reasons.append("No high-impact events in next 24h")

    return {
        "score": round(pct * 100), "verdict": _verdict_from_pct(pct),
        "reasons": reasons, "event_risk": bool(high_impact),
    }


def build_lane_verdicts(asset, signal_result: dict, news_items: list, econ_events: list) -> dict:
    """Combine the engine's technical/flow lanes with narrative/macro into the
    full 4-lane verdict block, plus a 'lanes_agreeing' summary count."""
    direction = signal_result["signal_type"]
    lanes = {
        "technical": signal_result["lane_technical"],
        "flow":      signal_result["lane_flow"],
        "narrative": narrative_lane(asset, direction, news_items),
        "macro":     macro_lane(asset, direction, signal_result.get("higher_tf_bias"), econ_events),
    }
    agreeing = sum(1 for l in lanes.values() if l["verdict"] in ("MODERATE", "HIGH"))
    return {**lanes, "lanes_agreeing": f"{agreeing}/4"}
