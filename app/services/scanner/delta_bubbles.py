"""
Delta Exchange India market bubble map — assets sized by trading activity
(turnover / open interest) and colored by direction (24h price change, or
for options, call/put open-interest skew), grouped by COIN CATEGORY rather
than Delta's internal contract-type field (perpetual/spot/options): Major
(a basket of the biggest coins — no individual single-coin tabs, since any
one major coin's data is already visible there), Mid-cap, Altcoin, Metals
(gold/silver-tracking tokens), and a separate Options tab (aggregated by
underlying — never folded into a coin tab, since an underlying's spot/perp
view and its options market are different things to look at).

Cheap by design: only hits the bulk /v2/tickers endpoint (no per-symbol
candle fetches like the MTF scanner), so it can be computed on demand with a
short cache rather than needing a scheduled prewarm job.
"""
from __future__ import annotations

import time

from app.services.data.fetcher import _http_session, _retry
from app.services.scanner.delta_mtf_scanner import _short_name

DELTA_BASE = "https://api.india.delta.exchange/v2"

# Basket shown on the "Major" tab — the handful of coins any trader would
# expect on a market-overview board. No individual single-coin tabs (BTC,
# ETH, LINK, etc.) — any specific major coin's data is already visible here.
MAJOR_SYMBOLS = ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD", "DOGEUSD", "ADAUSD", "LINKUSD"]

# Gold/silver-tracking perpetuals — verified live against Delta's product
# list (2026-08-29): exactly these three exist (Tether Gold, PAX Gold,
# iShares Silver Trust ONDO Token).
METAL_SYMBOLS = ["XAUTUSD", "PAXGUSD", "SLVONUSD"]

# After excluding Major + Metals, the remaining perpetuals are ranked by 24h
# turnover: the next MIDCAP_COUNT by volume are "Mid-cap", everything past
# that is "Altcoin". Turnover is the only ranking signal Delta's public API
# exposes (no market-cap data), so this is a volume-rank heuristic, not a
# true market-cap classification.
MIDCAP_COUNT = 20

# Underlyings that actually have an options market on Delta (verified live).
OPTIONS_UNDERLYINGS = ["BTC", "ETH", "XAUT"]

GROUPS = ("major", "midcap", "altcoin", "metals", "options")
GROUP_LABELS = {
    "major": "Major", "midcap": "Mid-cap", "altcoin": "Altcoin",
    "metals": "Metals", "options": "Options",
}


@_retry(max_attempts=3, backoff=1.5)
def _get_tickers(contract_types: str) -> list[dict]:
    resp = _http_session.get(
        f"{DELTA_BASE}/tickers",
        params={"contract_types": contract_types},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("result", [])


def _pct_change(open_: float, close: float) -> float:
    if not open_:
        return 0.0
    return (close - open_) / open_ * 100


# How much a big move can grow a bubble beyond its turnover-only baseline.
# Size used to be turnover alone, so a small-cap token swinging 15% looked
# exactly as "significant" as one sitting flat (same turnover, same size),
# while a big-cap coin's routine 1-2% move always dominated the map purely
# on volume. This is a multiplicative BOOST on top of turnover, not a
# replacement -- turnover still anchors the base size (an illiquid token
# pumping 50% on thin volume shouldn't visually outsize BTC), it just no
# longer ignores how much the price actually moved. Capped at a 25%+ move
# so one wild pump/dump doesn't blow the layout out.
MOVE_BOOST_CAP_PCT = 25.0


def _activity_score(turnover_usd: float, change_pct: float) -> float:
    move_boost = 1 + min(abs(change_pct), MOVE_BOOST_CAP_PCT) / MOVE_BOOST_CAP_PCT
    return turnover_usd * move_boost


def _ticker_to_bubble(t: dict) -> dict | None:
    symbol = t.get("symbol")
    close = float(t.get("close") or 0)
    open_ = float(t.get("open") or 0)
    volume = float(t.get("volume") or 0)
    turnover_usd = float(t.get("turnover_usd") or t.get("turnover") or 0)
    if not symbol or close <= 0 or turnover_usd <= 0:
        return None
    change_pct = round(_pct_change(open_, close), 3)
    return {
        "symbol": symbol,
        "label": _short_name(symbol, t.get("description")),
        "price": close,
        "change_pct": change_pct,
        "size_metric": _activity_score(turnover_usd, change_pct),
        "turnover_usd": turnover_usd,
        "volume": volume,
    }


def _options_bubbles() -> list[dict]:
    """One bubble per underlying that has an options market — size = total
    notional open interest (calls + puts), color = call/put OI skew (more
    call OI tilts bullish positioning, and vice versa). Individual option
    contracts (one per strike/expiry) aren't meaningful as their own
    bubbles, so this always aggregates by underlying."""
    calls = _get_tickers("call_options")
    puts = _get_tickers("put_options")

    bubbles = []
    for underlying in OPTIONS_UNDERLYINGS:
        call_oi = sum(float(t.get("oi_value_usd") or 0) for t in calls if t.get("underlying_asset_symbol") == underlying)
        put_oi = sum(float(t.get("oi_value_usd") or 0) for t in puts if t.get("underlying_asset_symbol") == underlying)
        total_oi = call_oi + put_oi
        if total_oi <= 0:
            continue
        skew_pct = (call_oi - put_oi) / total_oi * 100
        bubbles.append({
            "symbol": f"{underlying}_OPTIONS",
            "label": f"{underlying} Options",
            "price": None,
            "change_pct": round(skew_pct, 3),
            "size_metric": total_oi,
            "call_oi_usd": round(call_oi, 2),
            "put_oi_usd": round(put_oi, 2),
        })
    return bubbles


def get_bubbles(group: str) -> dict:
    if group not in GROUPS:
        raise ValueError(f"Unknown group: {group}")

    metric_label = "24h Turnover (USD)"
    color_label = "24h Change %"
    color_clamp_pct = 5.0
    bubbles: list[dict] = []

    if group == "options":
        bubbles = _options_bubbles()
        metric_label = "Open Interest (USD, calls + puts)"
        color_label = "Call/Put OI Skew %"
        color_clamp_pct = 30.0
    else:
        perp_tickers = _get_tickers("perpetual_futures")
        by_symbol = {t.get("symbol"): t for t in perp_tickers if t.get("symbol")}

        if group == "major":
            symbols = MAJOR_SYMBOLS
        elif group == "metals":
            symbols = METAL_SYMBOLS
        else:  # midcap / altcoin
            excluded = set(MAJOR_SYMBOLS) | set(METAL_SYMBOLS)
            remainder = [t for sym, t in by_symbol.items() if sym not in excluded]
            remainder_bubbles = [b for b in (_ticker_to_bubble(t) for t in remainder) if b]
            # Ranked by raw turnover, not the blended size_metric below --
            # the mid-cap/altcoin split is a volume-rank classification
            # (see MIDCAP_COUNT's docstring), and a huge % mover on thin
            # volume shouldn't jump the classification boundary just
            # because its DISPLAYED bubble is now boosted for visibility.
            remainder_bubbles.sort(key=lambda b: b["turnover_usd"], reverse=True)
            bubbles = remainder_bubbles[:MIDCAP_COUNT] if group == "midcap" else remainder_bubbles[MIDCAP_COUNT:]
            symbols = None

        if symbols is not None:
            for sym in symbols:
                t = by_symbol.get(sym)
                if t:
                    b = _ticker_to_bubble(t)
                    if b:
                        bubbles.append(b)

    return {
        "group": group,
        "group_label": GROUP_LABELS[group],
        "generated_at": int(time.time()),
        "metric_label": metric_label,
        "color_label": color_label,
        "color_clamp_pct": color_clamp_pct,
        "bubbles": bubbles,
    }
