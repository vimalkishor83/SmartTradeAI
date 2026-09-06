from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import get_jwt_identity
from app.models.asset import Asset
from app.models.saved_screen import SavedScreen
from app.models.mtf_watch_config import MtfWatchConfig, DEFAULT_MTF_WATCH_SYMBOLS
from app.auth.decorators import login_required
from app.services.data.fetcher import market_fetcher, blocked_data_markets
from app.services.indicators.calculator import calculate_all_indicators
from app.services.scanner.delta_mtf_scanner import (
    run_scan as run_delta_mtf_scan,
    get_status_for_symbols,
    list_symbols as list_delta_mtf_symbols,
)
from app.services.scanner.delta_bubbles import get_bubbles as get_delta_bubbles, GROUPS as DELTA_BUBBLE_GROUPS
from app.services.scanner import delta_market_screener as market_screener
from app.services.scanner import delta_indicator_scanner as indicator_scanner
from app.extensions import cache, db
import csv
import hashlib
import io
import json as _json
import threading
import time
from datetime import datetime

scanner_bp = Blueprint("scanner", __name__)

DELTA_SCANNER_CACHE_KEY = "delta_mtf_scanner_result"
DELTA_BUBBLES_CACHE_TTL = 25
DELTA_SCREENER_UNIVERSE_TTL = 120
# Longer than the 24h-stats screener's TTL: this universe needs a full
# per-symbol OHLCV fetch + indicator computation (~5-8s for 220 perpetuals
# on one timeframe), not just the bulk ticker endpoint, so it's worth
# holding onto longer between recomputes.
DELTA_INDICATOR_UNIVERSE_TTL = 180

_DELTA_SCANNER_BUILD_LOCK = threading.Lock()
_DELTA_BUBBLES_BUILD_LOCKS = {
    group: threading.Lock() for group in DELTA_BUBBLE_GROUPS
}
_DELTA_STATUS_BUILD_LOCK = threading.Lock()
_DELTA_SCREENER_UNIVERSE_BUILD_LOCK = threading.Lock()
_DELTA_INDICATOR_UNIVERSE_BUILD_LOCK = threading.Lock()

SCAN_FILTERS = [
    "strong_buy", "strong_sell", "breakout", "breakdown",
    "volume_spike", "52w_high", "52w_low", "gap_up", "gap_down",
    "rsi_oversold", "rsi_overbought",
]


@scanner_bp.route("/filters", methods=["GET"])
@login_required
def get_filters():
    return jsonify({"filters": SCAN_FILTERS}), 200


@scanner_bp.route("/run", methods=["POST"])
@login_required
def run_scan():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "request body must be a JSON object"}), 422
    filters = data.get("filters", ["strong_buy"])
    market = data.get("market")
    timeframe = data.get("timeframe", "1d")
    if not isinstance(filters, list) or not all(isinstance(f, str) for f in filters):
        return jsonify({"error": "filters must be a list of strings"}), 422
    filters = list(dict.fromkeys(f for f in filters if f in SCAN_FILTERS))
    if not filters:
        return jsonify({"error": "filters must include at least one supported filter"}), 422
    if market is not None and market not in Asset.MARKETS:
        return jsonify({"error": f"market must be one of {Asset.MARKETS}"}), 422
    from app.services.platform_config import FETCHABLE_TIMEFRAMES
    if timeframe not in FETCHABLE_TIMEFRAMES:
        return jsonify({"error": f"timeframe must be one of {FETCHABLE_TIMEFRAMES}"}), 422

    query = Asset.query.filter_by(is_active=True)
    if market:
        query = query.filter_by(market=market)
    assets = query.all()

    # Same rationale as prewarm_ta_cache/prewarm_ai_cache: fetch()/fetch_many()
    # already refuse a market paused in APIConfig (returns None), so an asset
    # in one just silently contributed nothing while still counting toward
    # "scanned" -- e.g. Indian stocks/indices paused mid-session made a scan
    # report "of 12 scanned" when only 7 were ever actually evaluated.
    blocked = blocked_data_markets()
    if blocked:
        assets = [a for a in assets if a.market not in blocked]

    if not assets:
        return jsonify({"results": [], "count": 0, "scanned": 0}), 200

    # Fetch all OHLCV up front via fetch_many: this batches Yahoo
    # (non-crypto) assets into ONE HTTP call for the timeframe (vs. N
    # separate per-asset calls) and fans out Delta/Binance crypto fetches
    # in parallel — the same network-batched path the prewarm jobs use.
    fetched = market_fetcher.fetch_many(assets, [timeframe], 220)

    results = []
    for asset in assets:
        df = fetched.get(asset.symbol, {}).get(timeframe)
        if df is None or len(df) < 60:
            continue
        try:
            ind = calculate_all_indicators(df)
            match = _apply_filters(df, ind, filters, timeframe)
            if not match:
                continue
            close = float(df["close"].iloc[-1])
            prev_close = float(df["close"].iloc[-2]) if len(df) > 1 else close
            results.append({
                "symbol": asset.symbol,
                "name": asset.name,
                "market": asset.market,
                "price": round(close, 4),
                "change_pct": round((close - prev_close) / prev_close * 100, 2),
                "rsi": ind.get("rsi"),
                "volume": float(df["volume"].iloc[-1]) if "volume" in df.columns else 0,
                "matched_filters": match,
            })
        except Exception:
            continue

    return jsonify({"results": results, "count": len(results), "scanned": len(assets)}), 200


@scanner_bp.route("/delta-mtf", methods=["GET"])
@login_required
def delta_mtf_scan():
    """Multi-timeframe EMA(9/21/50) + Supertrend(10,3) scan of every live
    Delta Exchange perpetual contract, ranked by volume. Served from the
    prewarm cache (refreshed every 5 min by the scheduler) so page loads
    are instant; force_refresh=1 bypasses it for an on-demand rescan."""
    force_refresh = request.args.get("force_refresh") in ("1", "true", "True")
    if not force_refresh:
        cached = cache.get(DELTA_SCANNER_CACHE_KEY)
        if cached is not None:
            return jsonify(cached), 200

    with _DELTA_SCANNER_BUILD_LOCK:
        if not force_refresh:
            cached = cache.get(DELTA_SCANNER_CACHE_KEY)
            if cached is not None:
                return jsonify(cached), 200
        result = run_delta_mtf_scan()
        cache.set(DELTA_SCANNER_CACHE_KEY, result, timeout=330)
    return jsonify(result), 200


@scanner_bp.route("/delta-mtf/watchlist", methods=["GET"])
@login_required
def get_mtf_watchlist():
    """The current user's configured symbol list for the MTF Scanner's
    "Common Coins" status panel — falls back to a sensible default set of
    majors when the user hasn't customized it yet."""
    user_id = get_jwt_identity()
    cfg = MtfWatchConfig.query.filter_by(user_id=user_id).first()
    symbols = cfg.symbols if cfg and cfg.symbols else DEFAULT_MTF_WATCH_SYMBOLS
    return jsonify({"symbols": symbols, "is_default": cfg is None}), 200


@scanner_bp.route("/delta-mtf/watchlist", methods=["POST"])
@login_required
def save_mtf_watchlist():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    symbols = data.get("symbols")
    if not isinstance(symbols, list) or not all(isinstance(s, str) for s in symbols):
        return jsonify({"error": "symbols must be a list of strings"}), 422
    symbols = [s.strip().upper() for s in symbols if s.strip()][:30]  # sane upper bound

    cfg = MtfWatchConfig.query.filter_by(user_id=user_id).first()
    if cfg:
        cfg.symbols = symbols
    else:
        cfg = MtfWatchConfig(user_id=user_id, symbols=symbols)
        db.session.add(cfg)
    db.session.commit()
    return jsonify(cfg.to_dict()), 200


@scanner_bp.route("/delta-mtf/symbols", methods=["GET"])
@login_required
def delta_mtf_symbols():
    """Full list of live Delta perpetual symbols + short display names, for
    the Common Coins search-and-select picker. Cheap ticker-list projection
    (no candle fetches), cached briefly since the universe barely changes
    minute to minute."""
    cache_key = "delta_mtf_symbols"
    cached = cache.get(cache_key)
    if cached is not None:
        return jsonify(cached), 200

    result = {"symbols": list_delta_mtf_symbols()}
    cache.set(cache_key, result, timeout=300)
    return jsonify(result), 200


@scanner_bp.route("/delta-mtf/status", methods=["GET"])
@login_required
def delta_mtf_status():
    """Live, UNFILTERED status (bullish/bearish/mixed) for the user's
    configured "Common Coins" list — unlike /delta-mtf, every requested
    symbol gets a row back regardless of whether it currently qualifies as
    a full BUY/SELL scan hit. Cheap (a handful of symbols), so computed
    fresh on every request rather than cached."""
    user_id = get_jwt_identity()
    cfg = MtfWatchConfig.query.filter_by(user_id=user_id).first()
    symbols = cfg.symbols if cfg and cfg.symbols else DEFAULT_MTF_WATCH_SYMBOLS
    symbols = list(dict.fromkeys(symbols))[:30]
    digest = hashlib.sha256(",".join(symbols).encode("utf-8")).hexdigest()[:20]
    cache_key = f"delta_mtf_status_{digest}"
    cached = cache.get(cache_key)
    if cached is not None:
        return jsonify(cached), 200
    with _DELTA_STATUS_BUILD_LOCK:
        cached = cache.get(cache_key)
        if cached is not None:
            return jsonify(cached), 200
        result = get_status_for_symbols(symbols)
        cache.set(cache_key, result, timeout=25)
    return jsonify(result), 200


@scanner_bp.route("/delta-bubbles", methods=["GET"])
@login_required
def delta_bubbles():
    """Delta Exchange India market bubble map: assets sized by trading
    activity, colored by direction, grouped by coin category (Major,
    individual majors, Mid-cap, Altcoin, Metals) rather than Delta's
    internal contract-type field."""
    group = request.args.get("group", "major")
    if group not in DELTA_BUBBLE_GROUPS:
        return jsonify({"error": f"group must be one of {DELTA_BUBBLE_GROUPS}"}), 422

    cache_key = f"delta_bubbles_{group}"
    cached = cache.get(cache_key)
    if cached is not None:
        return jsonify(cached), 200

    with _DELTA_BUBBLES_BUILD_LOCKS[group]:
        cached = cache.get(cache_key)
        if cached is not None:
            return jsonify(cached), 200
        result = get_delta_bubbles(group)
        cache.set(cache_key, result, timeout=DELTA_BUBBLES_CACHE_TTL)
    return jsonify(result), 200


def _delta_screener_universe_cache_key(asset_type: str) -> str:
    return f"delta_screener_universe_{asset_type}"


def get_delta_screener_universe(asset_type: str) -> list:
    """Cached universe lookup shared by the API route and the scheduler
    prewarm job — the expensive per-symbol RSI computation only runs once
    per DELTA_SCREENER_UNIVERSE_TTL window regardless of how many distinct
    filter combinations users try against it."""
    cache_key = _delta_screener_universe_cache_key(asset_type)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    with _DELTA_SCREENER_UNIVERSE_BUILD_LOCK:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        universe = market_screener._compute_universe(asset_type)
        cache.set(cache_key, universe, timeout=DELTA_SCREENER_UNIVERSE_TTL)
    return universe


class _ScreenerRequestError(Exception):
    def __init__(self, message: str):
        self.message = message


def _parse_screener_request(args) -> tuple[str, list, str]:
    """Shared query-param parsing for the JSON and CSV screener endpoints —
    keeps the two response formats from drifting on how asset_type/preset/
    conditions/combinator are read and validated."""
    asset_type = args.get("asset_type", "perpetual_futures")
    if asset_type not in market_screener.ASSET_TYPES:
        raise _ScreenerRequestError(f"asset_type must be one of {market_screener.ASSET_TYPES}")

    preset_key = args.get("preset")
    if preset_key:
        preset = market_screener.PRESETS.get(preset_key)
        if not preset:
            raise _ScreenerRequestError(f"Unknown preset '{preset_key}'")
        conditions = preset["conditions"]
    else:
        raw = args.get("conditions", "[]")
        try:
            conditions = _json.loads(raw)
            if not isinstance(conditions, list):
                raise ValueError
        except (ValueError, TypeError):
            raise _ScreenerRequestError("conditions must be a JSON list")

    if not isinstance(conditions, list) or len(conditions) > 20 or not all(isinstance(c, dict) for c in conditions):
        raise _ScreenerRequestError("conditions must be a list of at most 20 objects")
    combinator = args.get("combinator", "AND").upper()
    if combinator not in ("AND", "OR"):
        raise _ScreenerRequestError("combinator must be AND or OR")
    return asset_type, conditions, combinator


@scanner_bp.route("/delta-market-screener", methods=["GET"])
@login_required
def delta_market_screener():
    """Flexible WHERE-condition screener over Delta Exchange India contracts.

    Query params:
      asset_type: perpetual_futures | spot | move_options (default perpetual_futures)
      conditions: JSON-encoded list of {field, op, value, value2?, abs?}
      combinator: AND | OR (default AND)
      preset: a key from delta_market_screener.PRESETS — shorthand for a
        common conditions list, applied instead of `conditions` when given.
    """
    try:
        asset_type, conditions, combinator = _parse_screener_request(request.args)
    except _ScreenerRequestError as exc:
        return jsonify({"error": exc.message}), 422

    universe = get_delta_screener_universe(asset_type)
    results = market_screener.run_screener(universe, conditions, combinator)
    results = sorted(results, key=lambda r: r["turnover_usd"], reverse=True)

    return jsonify({
        "asset_type": asset_type,
        "generated_at": int(time.time()),
        "universe_size": len(universe),
        "matched": len(results),
        "fields": market_screener.FIELDS,
        "operators": market_screener.OPERATORS,
        "presets": {k: v["label"] for k, v in market_screener.PRESETS.items()},
        "results": results,
    }), 200


@scanner_bp.route("/delta-market-screener/export.csv", methods=["GET"])
@login_required
def delta_market_screener_export_csv():
    """Export the current filter's results as CSV — same query params as
    the JSON endpoint above, so "Export" downloads exactly what's on screen."""
    try:
        asset_type, conditions, combinator = _parse_screener_request(request.args)
    except _ScreenerRequestError as exc:
        return jsonify({"error": exc.message}), 422

    universe = get_delta_screener_universe(asset_type)
    results = market_screener.run_screener(universe, conditions, combinator)
    results = sorted(results, key=lambda r: r["turnover_usd"], reverse=True)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Symbol", "Price", "24h Change %", "24h Volume", "RSI(14)", "Funding %", "Open Interest"])
    for r in results:
        writer.writerow([
            r["symbol"], r["price"], r["change_24h_pct"], r["volume_24h"],
            r["rsi_14"] if r["rsi_14"] is not None else "",
            r["funding_pct"] if r["funding_pct"] is not None else "",
            r["open_interest"],
        ])

    today = datetime.utcnow().strftime("%Y-%m-%d")
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=delta_screener_{asset_type}_{today}.csv"},
    )


@scanner_bp.route("/delta-market-screener/saved", methods=["GET"])
@login_required
def list_saved_screens():
    user_id = get_jwt_identity()
    screens = SavedScreen.query.filter_by(user_id=user_id).order_by(SavedScreen.updated_at.desc()).all()
    return jsonify({"screens": [s.to_dict() for s in screens]}), 200


@scanner_bp.route("/delta-market-screener/saved", methods=["POST"])
@login_required
def save_screen():
    """Create or update (by name) a saved screen for the current user."""
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    if len(name) > 120:
        return jsonify({"error": "name must be 120 characters or fewer"}), 422

    asset_type = data.get("asset_type", "perpetual_futures")
    if asset_type not in market_screener.ASSET_TYPES:
        return jsonify({"error": f"asset_type must be one of {market_screener.ASSET_TYPES}"}), 422

    conditions = data.get("conditions", [])
    if (not isinstance(conditions, list) or len(conditions) > 20
            or not all(isinstance(c, dict) for c in conditions)):
        return jsonify({"error": "conditions must be a list of at most 20 objects"}), 422

    combinator = data.get("combinator", "AND")
    if combinator not in ("AND", "OR"):
        return jsonify({"error": "combinator must be AND or OR"}), 422

    screen = SavedScreen.query.filter_by(user_id=user_id, name=name).first()
    if screen:
        screen.asset_type = asset_type
        screen.conditions = conditions
        screen.combinator = combinator
    else:
        screen = SavedScreen(user_id=user_id, name=name, asset_type=asset_type,
                             conditions=conditions, combinator=combinator)
        db.session.add(screen)
    db.session.commit()
    return jsonify(screen.to_dict()), 200


@scanner_bp.route("/delta-market-screener/saved/<int:screen_id>", methods=["DELETE"])
@login_required
def delete_saved_screen(screen_id):
    user_id = get_jwt_identity()
    screen = SavedScreen.query.filter_by(id=screen_id, user_id=user_id).first_or_404()
    db.session.delete(screen)
    db.session.commit()
    return jsonify({"message": "Deleted"}), 200


def _delta_indicator_universe_cache_key(asset_type: str, timeframe: str) -> str:
    return f"delta_indicator_universe_{asset_type}_{timeframe}"


def get_delta_indicator_universe(asset_type: str, timeframe: str) -> list:
    """Cached universe lookup, shared by the API route and the scheduler
    prewarm job — mirrors get_delta_screener_universe's two-tier design so
    trying different indicator conditions on the same timeframe is instant."""
    cache_key = _delta_indicator_universe_cache_key(asset_type, timeframe)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    with _DELTA_INDICATOR_UNIVERSE_BUILD_LOCK:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        universe = indicator_scanner.compute_universe(asset_type, timeframe)
        cache.set(cache_key, universe, timeout=DELTA_INDICATOR_UNIVERSE_TTL)
    return universe


@scanner_bp.route("/delta-indicator-screener", methods=["GET"])
@login_required
def delta_indicator_screener():
    """Indicator-crossover screener over Delta Exchange India contracts.

    Query params:
      asset_type: perpetual_futures | spot | move_options (default perpetual_futures)
      timeframe: 5m | 15m | 1h (default 15m) — the candle each indicator is computed on
      conditions: JSON-encoded list of condition objects, e.g.
        {"left": {"type":"indicator","field":"ema9"},
         "comparison": "crosses_above",
         "right": {"type":"indicator","field":"ema20"}}
        or a static threshold:
        {"left": {"type":"indicator","field":"rsi14"},
         "comparison": "is_below", "right": {"type":"number","value":30}}
        or a range: {"left": {...}, "comparison": "is_between", "low": 20, "high": 30}
      combinator: AND | OR (default AND)
    """
    asset_type = request.args.get("asset_type", "perpetual_futures")
    timeframe = request.args.get("timeframe", "15m")
    if asset_type not in indicator_scanner.ASSET_TYPES:
        return jsonify({"error": f"asset_type must be one of {indicator_scanner.ASSET_TYPES}"}), 422
    if timeframe not in indicator_scanner.TIMEFRAMES:
        return jsonify({"error": f"timeframe must be one of {indicator_scanner.TIMEFRAMES}"}), 422

    raw = request.args.get("conditions", "[]")
    try:
        conditions = _json.loads(raw)
        if not isinstance(conditions, list):
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "conditions must be a JSON list"}), 422

    if len(conditions) > 20 or not all(isinstance(c, dict) for c in conditions):
        return jsonify({"error": "conditions must be a list of at most 20 objects"}), 422
    combinator = request.args.get("combinator", "AND").upper()
    if combinator not in ("AND", "OR"):
        return jsonify({"error": "combinator must be AND or OR"}), 422

    universe = get_delta_indicator_universe(asset_type, timeframe)
    result = indicator_scanner.filter_universe(universe, conditions, combinator)
    result["asset_type"] = asset_type
    result["timeframe"] = timeframe
    return jsonify(result), 200


def _apply_filters(df, ind, filters, timeframe: str = "1d") -> list:
    matched = []
    close = float(df["close"].iloc[-1])
    open_ = float(df["open"].iloc[-1])
    prev_close = float(df["close"].iloc[-2]) if len(df) > 1 else close
    rsi = ind.get("rsi") or 50
    ema20 = ind.get("ema20") or close
    ema50 = ind.get("ema50") or close
    macd_hist = ind.get("macd_hist") or 0
    avg_vol = df["volume"].rolling(20).mean().iloc[-1] if "volume" in df.columns else 1
    curr_vol = df["volume"].iloc[-1] if "volume" in df.columns else 0
    high_52 = df["high"].rolling(252).max().iloc[-1] if len(df) >= 252 else df["high"].max()
    low_52 = df["low"].rolling(252).min().iloc[-1] if len(df) >= 252 else df["low"].min()

    checks = {
        "strong_buy": ema20 > ema50 and macd_hist > 0 and 50 < rsi < 70,
        # Mirror of strong_buy's bounded RSI band — previously only checked
        # `rsi < 50` with no lower bound, so it fired even at RSI=5 (deeply
        # oversold), self-contradicting rsi_oversold (a bounce candidate, not
        # a fresh sell signal) for the exact same asset.
        "strong_sell": ema20 < ema50 and macd_hist < 0 and 30 < rsi < 50,
        "breakout": close > high_52 * 0.99,
        "breakdown": close < low_52 * 1.01,
        "volume_spike": avg_vol > 0 and curr_vol > avg_vol * 2,
        "52w_high": close >= high_52 * 0.98,
        "52w_low": close <= low_52 * 1.02,
        # A "gap" is conventionally an overnight/session gap, only
        # meaningful on the daily timeframe — the previous "candle" close vs
        # this candle's open on an intraday timeframe (5m/1h/etc.) is just
        # ordinary intra-session price drift, not a gap by any trader's
        # definition, and was flooding intraday scans with false positives.
        "gap_up": timeframe == "1d" and open_ > prev_close * 1.01,
        "gap_down": timeframe == "1d" and open_ < prev_close * 0.99,
        "rsi_oversold": rsi < 30,
        "rsi_overbought": rsi > 70,
    }

    for f in filters:
        if checks.get(f, False):
            matched.append(f)

    return matched
