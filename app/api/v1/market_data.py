from flask import Blueprint, request, jsonify
from app.models.asset import Asset
from app.extensions import db, cache, limiter
from app.auth.decorators import login_required
from app.services.data.fetcher import market_fetcher
from app.services.indicators.calculator import calculate_all_indicators
from app.services.sentiment.engine import calculate_sentiment
from sqlalchemy.orm import joinedload
import pandas as pd

market_data_bp = Blueprint("market_data", __name__)


@market_data_bp.route("/<int:asset_id>/ohlcv", methods=["GET"])
@login_required
def get_ohlcv(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    timeframe = request.args.get("timeframe", "1h")
    limit = min(int(request.args.get("limit", 200)), 1000)

    df = market_fetcher.fetch(asset, timeframe, limit)
    if df is None:
        return jsonify({"error": "Data unavailable"}), 503

    records = []
    for ts, row in df.iterrows():
        records.append({
            "t": int(ts.timestamp() * 1000) if hasattr(ts, "timestamp") else str(ts),
            "o": round(float(row["open"]), 6),
            "h": round(float(row["high"]), 6),
            "l": round(float(row["low"]), 6),
            "c": round(float(row["close"]), 6),
            "v": round(float(row.get("volume", 0)), 2),
        })

    return jsonify({"symbol": asset.symbol, "timeframe": timeframe, "data": records}), 200


@market_data_bp.route("/<int:asset_id>/indicators", methods=["GET"])
@login_required
def get_indicators(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    timeframe = request.args.get("timeframe", "1h")

    limit = 500 if timeframe == "1d" else 220
    df = market_fetcher.fetch(asset, timeframe, limit)
    if df is None:
        return jsonify({"error": "Data unavailable"}), 503

    indicators = calculate_all_indicators(df)
    return jsonify({"symbol": asset.symbol, "timeframe": timeframe, "indicators": indicators}), 200


@market_data_bp.route("/<int:asset_id>/sentiment", methods=["GET"])
@login_required
def get_sentiment(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    timeframe = request.args.get("timeframe", "1h")

    df = market_fetcher.fetch(asset, timeframe, 100)
    if df is None:
        return jsonify({"error": "Data unavailable"}), 503

    indicators = calculate_all_indicators(df)
    sentiment = calculate_sentiment(indicators)
    return jsonify({"symbol": asset.symbol, "sentiment": sentiment}), 200


@market_data_bp.route("/ta-summary", methods=["GET"])
@login_required
def ta_summary():
    from app.auth.decorators import get_current_user
    from app.models.user import UserAssetPreference
    user   = get_current_user()
    market = request.args.get("market") or "all"

    # ── Serve from pre-warmed global cache (near-instant) ────────
    global_cache = cache.get("ta_summary_all")
    if global_cache:
        prefs = {p.asset_id: p.enabled
                 for p in UserAssetPreference.query.filter_by(user_id=user.id).all()}
        assets = global_cache["assets"]
        if market != "all":
            assets = [a for a in assets if a.get("market") == market]
        if prefs:
            assets = [a for a in assets if prefs.get(a["id"], True)]
        return jsonify({"assets": assets, "timeframes": global_cache["timeframes"]}), 200

    # ── Cold path: compute on-demand (first boot before scheduler runs) ──
    prefs = {p.asset_id: p.enabled for p in UserAssetPreference.query.filter_by(user_id=user.id).all()}
    tfs = ["5m", "15m", "30m", "1h", "2h", "4h", "1d"]
    asset_q = Asset.query.filter_by(is_active=True)
    if market != "all":
        asset_q = asset_q.filter_by(market=market)
    all_assets = asset_q.order_by(Asset.market, Asset.symbol).all()
    assets = [a for a in all_assets if prefs.get(a.id, True)] if prefs else all_assets

    all_data = market_fetcher.fetch_many(assets, tfs, limit=200)

    def _process_asset(asset):
        sym  = asset.symbol
        dfs  = all_data.get(sym, {})
        row  = {
            "id": asset.id, "symbol": sym, "name": asset.name, "market": asset.market,
            "tf": {}, "price": None, "open": None, "high": None, "low": None,
            "change": None, "change_pct": None, "volume": None, "time": None,
        }
        df_price = dfs.get("1h")
        if df_price is not None and len(df_price) >= 2:
            try:
                last  = df_price.iloc[-1];  prev = df_price.iloc[-2]
                price = float(last["close"]); chg = price - float(prev["close"])
                row.update({"price": price, "open": float(last["open"]),
                            "high": float(last["high"]), "low": float(last["low"]),
                            "change": round(chg, 6),
                            "change_pct": round(chg / float(prev["close"]) * 100, 2) if prev["close"] else 0,
                            "volume": float(last.get("volume", 0)),
                            "time": df_price.index[-1].strftime("%H:%M") if hasattr(df_price.index[-1], "strftime") else ""})
            except Exception:
                pass
        for tf in tfs:
            try:
                df = dfs.get(tf)
                if df is None or len(df) < 52: row["tf"][tf] = None; continue
                ind = calculate_all_indicators(df)
                row["tf"][tf] = _compute_ta_rating(ind, float(df["close"].iloc[-1]))
            except Exception:
                row["tf"][tf] = None
        return row

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(8, len(assets))) as ex:
        result = list(ex.map(_process_asset, assets))

    payload = {"assets": result, "timeframes": tfs}
    # Store as global cache so next request is instant
    cache.set("ta_summary_all", {"assets": result, "timeframes": tfs}, timeout=150)
    return jsonify(payload), 200


def _compute_ta_rating(ind, close):
    """Score indicators as buy/sell/neutral, return summary rating."""
    buy = sell = neutral = 0

    def vote(signal):
        nonlocal buy, sell, neutral
        if signal == "buy":    buy    += 1
        elif signal == "sell": sell   += 1
        else:                  neutral += 1

    rsi = ind.get("rsi")
    if rsi:
        vote("buy" if rsi < 30 else "sell" if rsi > 70 else "neutral")

    macd = ind.get("macd"); macd_sig = ind.get("macd_signal")
    if macd is not None and macd_sig is not None:
        vote("buy" if macd > macd_sig else "sell" if macd < macd_sig else "neutral")

    cci = ind.get("cci")
    if cci:
        vote("buy" if cci < -100 else "sell" if cci > 100 else "neutral")

    roc = ind.get("roc")
    if roc:
        vote("buy" if roc > 0 else "sell" if roc < 0 else "neutral")

    stoch_k = ind.get("stoch_rsi_k"); stoch_d = ind.get("stoch_rsi_d")
    if stoch_k is not None and stoch_d is not None:
        vote("buy" if stoch_k < 20 else "sell" if stoch_k > 80 else "neutral")

    # MAs vs price
    for ma_key in ["ema20", "ema50", "ema100", "ema200", "sma20", "sma50"]:
        ma = ind.get(ma_key)
        if ma:
            vote("buy" if close > ma else "sell")

    # Ichimoku
    tenkan = ind.get("ichimoku_tenkan"); kijun = ind.get("ichimoku_kijun")
    if tenkan and kijun:
        vote("buy" if tenkan > kijun else "sell")

    # Bollinger
    bb_upper = ind.get("bb_upper"); bb_lower = ind.get("bb_lower")
    if bb_upper and bb_lower:
        vote("buy" if close < bb_lower else "sell" if close > bb_upper else "neutral")

    # Supertrend
    st_dir = ind.get("supertrend_direction")
    if st_dir:
        vote("buy" if st_dir == "up" else "sell")

    # CMF
    cmf = ind.get("cmf")
    if cmf is not None:
        vote("buy" if cmf > 0 else "sell" if cmf < 0 else "neutral")

    total = buy + sell + neutral
    if total == 0:
        return None

    score = (buy - sell) / total  # -1 to +1
    if score >= 0.6:    label = "Strong Buy"
    elif score >= 0.2:  label = "Buy"
    elif score <= -0.6: label = "Strong Sell"
    elif score <= -0.2: label = "Sell"
    else:               label = "Neutral"

    return {"rating": label, "buy": buy, "sell": sell, "neutral": neutral, "score": round(score, 2)}


@market_data_bp.route("/ai-summary", methods=["GET"])
@login_required
@limiter.limit("10 per minute;60 per hour")
def ai_summary():
    """Batch AI predictions for all assets × key timeframes — powers the AI Ratings grid."""
    from app.auth.decorators import get_current_user
    from app.models.prediction import Prediction
    from app.models.user import UserAssetPreference
    from app.services.ai.predictor import ai_predictor
    from datetime import datetime, timedelta
    from concurrent.futures import ThreadPoolExecutor

    user   = get_current_user()
    market = request.args.get("market") or "all"

    # ── Serve from pre-warmed global cache (near-instant) ────────
    global_ai = cache.get("ai_summary_all")
    if global_ai:
        prefs = {p.asset_id: p.enabled
                 for p in UserAssetPreference.query.filter_by(user_id=user.id).all()}
        assets = global_ai["assets"]
        if market != "all":
            assets = [a for a in assets if a.get("market") == market]
        if prefs:
            assets = [a for a in assets if prefs.get(a["id"], True)]
        return jsonify({"assets": assets, "timeframes": global_ai["timeframes"]}), 200

    tfs      = ["5m", "15m", "1h", "4h", "1d"]
    prefs    = {p.asset_id: p.enabled for p in UserAssetPreference.query.filter_by(user_id=user.id).all()}
    asset_q  = Asset.query.filter_by(is_active=True)
    if market != "all":
        asset_q = asset_q.filter_by(market=market)
    all_assets = asset_q.order_by(Asset.market, Asset.symbol).all()
    assets     = [a for a in all_assets if prefs.get(a.id, True)] if prefs else all_assets

    cache_cutoff = datetime.utcnow() - timedelta(minutes=30)

    # Pull all recent cached predictions in one query
    asset_ids = [a.id for a in assets]
    recent_preds = Prediction.query.filter(
        Prediction.asset_id.in_(asset_ids),
        Prediction.timeframe.in_(tfs),
        Prediction.predicted_at >= cache_cutoff,
    ).all()

    pred_map = {}
    for p in recent_preds:
        pred_map[(p.asset_id, p.timeframe)] = p.to_dict()

    all_data = market_fetcher.fetch_many(assets, tfs, limit=220)

    def _process(asset):
        row = {"id": asset.id, "symbol": asset.symbol, "name": asset.name, "market": asset.market, "tf": {}}
        for tf in tfs:
            key = (asset.id, tf)
            if key in pred_map:
                p = pred_map[key]
                # Values already stored as 0–100 in DB
                row["tf"][tf] = {
                    "direction":    p["predicted_direction"],
                    "confidence":   round(float(p["confidence"]),          1),
                    "bullish_prob": round(float(p["bullish_probability"]),  1),
                    "bearish_prob": round(float(p["bearish_probability"]),  1),
                }
                continue
            df = all_data.get(asset.symbol, {}).get(tf)
            try:
                # predictor handles None / short df internally, returns neutral default
                result = ai_predictor.predict(df, asset.symbol, tf)
                # Only persist to DB if we had real data (avoid saving default neutral)
                if df is not None and len(df) >= 100:
                    pred = Prediction(
                        asset_id=asset.id, timeframe=tf,
                        model_name=result["model_name"],
                        bullish_probability=result["bullish_probability"],
                        bearish_probability=result["bearish_probability"],
                        predicted_direction=result["predicted_direction"],
                        predicted_target=result.get("predicted_target"),
                        predicted_stop=result.get("predicted_stop"),
                        confidence=result["confidence"],
                        valid_until=datetime.utcnow() + timedelta(hours=4),
                    )
                    db.session.add(pred)
                # Values from predictor are already 0–100
                row["tf"][tf] = {
                    "direction":    result["predicted_direction"],
                    "confidence":   round(float(result["confidence"]),         1),
                    "bullish_prob": round(float(result["bullish_probability"]), 1),
                    "bearish_prob": round(float(result["bearish_probability"]), 1),
                }
            except Exception:
                row["tf"][tf] = {"direction": "neutral", "confidence": 50.0, "bullish_prob": 50.0, "bearish_prob": 50.0}
        return row

    with ThreadPoolExecutor(max_workers=min(6, len(assets))) as ex:
        result = list(ex.map(_process, assets))

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    payload = {"assets": result, "timeframes": tfs}
    cache.set("ai_summary_all", payload, timeout=150)
    return jsonify(payload), 200


@market_data_bp.route("/live-prices", methods=["GET"])
@login_required
@limiter.exempt
def live_prices():
    """Return cached live prices from Binance WebSocket stream (crypto only).
    Falls back to REST fetch_ticker for assets not in stream cache."""
    from app.services.data.binance_stream import get_all_live_prices
    cached = get_all_live_prices()
    # Supplement with any assets not yet in stream cache
    if not cached:
        assets = Asset.query.filter_by(market="crypto", is_active=True,
                                       data_source="binance").all()
        for a in assets:
            t = market_fetcher.fetch_ticker(a)
            if t:
                cached[a.symbol] = t
    return jsonify({"prices": cached}), 200


@market_data_bp.route("/heatmap", methods=["GET"])
@login_required
@limiter.exempt
@cache.cached(timeout=180, key_prefix="market_heatmap")
def get_heatmap():
    # Limit to key assets for speed — full heatmap would be too slow without paid APIs
    KEY_SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
                   "EURUSD","USDINR","XAUUSD","XAGUSD",
                   "NIFTY50","BANKNIFTY","SENSEX","RELIANCE","TCS","INFY"]
    assets = Asset.query.filter(Asset.symbol.in_(KEY_SYMBOLS), Asset.is_active == True).all()
    heatmap = []
    for asset in assets:
        try:
            df = market_fetcher.fetch(asset, "1d", 3)
            if df is not None and len(df) >= 2:
                price  = float(df["close"].iloc[-1])
                prev   = float(df["close"].iloc[-2])
                change = (price - prev) / prev * 100 if prev else 0
                heatmap.append({
                    "asset_id":   asset.id,
                    "symbol":     asset.symbol,
                    "name":       asset.name,
                    "market":     asset.market,
                    "price":      round(price, 4),
                    "change_pct": round(change, 2),
                })
        except Exception:
            continue
    return jsonify({"heatmap": heatmap}), 200


# ─── Advanced Analysis endpoint ───────────────────────────────────────────────

import numpy as np


def _pivot_highs_lows(highs, lows):
    ph, pl = [], []
    for i in range(1, len(highs) - 1):
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            ph.append(i)
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            pl.append(i)
    return ph, pl


def _compute_fibonacci(highs, lows):
    n = min(100, len(highs))
    h_slice = highs[-n:]
    l_slice = lows[-n:]
    swing_high = float(max(h_slice))
    swing_low  = float(min(l_slice))
    diff = swing_high - swing_low
    retracement_ratios = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
    extension_ratios   = [1.272, 1.618, 2.0]
    levels = []
    for r in retracement_ratios:
        levels.append({"label": str(r), "price": round(swing_high - diff * r, 6), "type": "retracement"})
    for r in extension_ratios:
        levels.append({"label": str(r), "price": round(swing_high + diff * (r - 1.0), 6), "type": "extension"})
    return {"swing_high": round(swing_high, 6), "swing_low": round(swing_low, 6), "levels": levels}


def _compute_liquidity(highs, lows, timestamps):
    n = min(100, len(highs))
    h_slice = list(highs[-n:])
    l_slice = list(lows[-n:])

    def find_clusters(values, label_type):
        clusters = []
        used = [False] * len(values)
        for i in range(len(values)):
            if used[i]:
                continue
            ref = values[i]
            if ref == 0:
                continue
            cluster_vals = [ref]
            cluster_idx  = [i]
            for j in range(i + 1, len(values)):
                if used[j]:
                    continue
                if abs(values[j] - ref) / ref <= 0.0015:
                    cluster_vals.append(values[j])
                    cluster_idx.append(j)
                    used[j] = True
            if len(cluster_vals) >= 2:
                used[i] = True
                hits = len(cluster_vals)
                strength = "strong" if hits >= 4 else "medium" if hits >= 3 else "weak"
                clusters.append({
                    "type": label_type,
                    "price": round(float(sum(cluster_vals) / len(cluster_vals)), 6),
                    "hits": hits,
                    "strength": strength
                })
        return clusters

    buy_side  = find_clusters(l_slice, "buy_side")
    sell_side = find_clusters(h_slice, "sell_side")

    # Keep only the strongest/most-recent pools — full list would flood the chart
    strength_rank = {"strong": 3, "medium": 2, "weak": 1}
    buy_side  = sorted(buy_side,  key=lambda c: (strength_rank[c["strength"]], c["hits"]), reverse=True)[:6]
    sell_side = sorted(sell_side, key=lambda c: (strength_rank[c["strength"]], c["hits"]), reverse=True)[:6]
    buy_side.sort(key=lambda c: c["price"], reverse=True)
    sell_side.sort(key=lambda c: c["price"], reverse=True)
    return {"buy_side": buy_side, "sell_side": sell_side}


def _compute_fvg(opens, highs, lows, closes, timestamps):
    fvgs = []
    for i in range(1, len(highs) - 1):
        if lows[i - 1] > highs[i + 1]:
            top    = float(lows[i - 1])
            bottom = float(highs[i + 1])
            filled = any(highs[k] >= top for k in range(i + 2, len(highs)))
            fvgs.append({"type": "bearish", "top": round(top, 6), "bottom": round(bottom, 6),
                         "time": int(timestamps[i]), "filled": filled})
        elif highs[i - 1] < lows[i + 1]:
            top    = float(lows[i + 1])
            bottom = float(highs[i - 1])
            filled = any(lows[k] <= bottom for k in range(i + 2, len(lows)))
            fvgs.append({"type": "bullish", "top": round(top, 6), "bottom": round(bottom, 6),
                         "time": int(timestamps[i]), "filled": filled})
    return fvgs[-10:]


def _compute_order_blocks(opens, highs, lows, closes, timestamps):
    obs = []
    threshold = 0.005
    for i in range(1, len(closes) - 1):
        move = (closes[i + 1] - closes[i]) / closes[i] if closes[i] else 0
        if move > threshold and closes[i] < opens[i]:
            top    = float(opens[i])
            bottom = float(closes[i])
            broken = any(lows[k] < bottom for k in range(i + 1, len(lows)))
            obs.append({"type": "bullish", "top": round(top, 6), "bottom": round(bottom, 6),
                        "time": int(timestamps[i]), "broken": broken})
        elif move < -threshold and closes[i] > opens[i]:
            top    = float(closes[i])
            bottom = float(opens[i])
            broken = any(highs[k] > top for k in range(i + 1, len(highs)))
            obs.append({"type": "bearish", "top": round(top, 6), "bottom": round(bottom, 6),
                        "time": int(timestamps[i]), "broken": broken})
    return obs[-8:]


def _compute_market_structure(highs, lows, timestamps):
    ph_idx, pl_idx = _pivot_highs_lows(highs, lows)
    if len(ph_idx) < 2 or len(pl_idx) < 2:
        return {"points": [], "trend": "ranging"}

    sh_vals = [(ph_idx[i], float(highs[ph_idx[i]]), "H") for i in range(len(ph_idx))]
    sl_vals = [(pl_idx[i], float(lows[pl_idx[i]]), "L")  for i in range(len(pl_idx))]
    all_pts  = sorted(sh_vals + sl_vals, key=lambda x: x[0])

    points = []
    prev_high = None
    prev_low  = None
    for idx, price, kind in all_pts:
        if kind == "H":
            label = ("HH" if prev_high is None or price > prev_high else "LH")
            prev_high = price
        else:
            label = ("LL" if prev_low is None or price < prev_low else "HL")
            prev_low = price
        points.append({"type": label, "price": round(price, 6), "time": int(timestamps[idx])})

    recent = points[-6:]
    hh = sum(1 for p in recent if p["type"] == "HH")
    hl = sum(1 for p in recent if p["type"] == "HL")
    ll = sum(1 for p in recent if p["type"] == "LL")
    lh = sum(1 for p in recent if p["type"] == "LH")
    if hh >= 1 and hl >= 1:
        trend = "uptrend"
    elif ll >= 1 and lh >= 1:
        trend = "downtrend"
    else:
        trend = "ranging"
    return {"points": points[-10:], "trend": trend}


def _linear_regression_line(xs, ys):
    n = len(xs)
    if n < 2:
        return 0, ys[0] if ys else 0
    sx  = sum(xs)
    sy  = sum(ys)
    sxy = sum(xs[i] * ys[i] for i in range(n))
    sxx = sum(xs[i] ** 2 for i in range(n))
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0, sy / n
    slope     = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


def _compute_trend_lines(highs, lows, timestamps):
    ph_idx, pl_idx = _pivot_highs_lows(highs, lows)
    lines = []
    if len(ph_idx) >= 2:
        idx_list = ph_idx[-3:]
        xs = list(range(len(idx_list)))
        ys = [float(highs[i]) for i in idx_list]
        slope, intercept = _linear_regression_line(xs, ys)
        y1 = intercept
        y2 = slope * (len(idx_list) - 1) + intercept
        lines.append({
            "type": "resistance",
            "x1_time": int(timestamps[idx_list[0]]),
            "y1": round(y1, 6),
            "x2_time": int(timestamps[idx_list[-1]]),
            "y2": round(y2, 6),
            "slope": round(slope, 8)
        })
    if len(pl_idx) >= 2:
        idx_list = pl_idx[-3:]
        xs = list(range(len(idx_list)))
        ys = [float(lows[i]) for i in idx_list]
        slope, intercept = _linear_regression_line(xs, ys)
        y1 = intercept
        y2 = slope * (len(idx_list) - 1) + intercept
        lines.append({
            "type": "support",
            "x1_time": int(timestamps[idx_list[0]]),
            "y1": round(y1, 6),
            "x2_time": int(timestamps[idx_list[-1]]),
            "y2": round(y2, 6),
            "slope": round(slope, 8)
        })
    return lines


def _compute_vwap(opens, highs, lows, closes, volumes, timestamps):
    typical = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(len(closes))]
    cum_tp_v = 0.0
    cum_v    = 0.0
    result = []
    for i in range(len(closes)):
        cum_tp_v += typical[i] * volumes[i]
        cum_v    += volumes[i]
        vwap = cum_tp_v / cum_v if cum_v > 0 else closes[i]
        result.append({"t": int(timestamps[i]), "vwap": round(float(vwap), 6)})
    return result


def _compute_volume_profile(highs, lows, closes, volumes, buckets=20):
    price_min = float(min(lows))
    price_max = float(max(highs))
    if price_max <= price_min:
        return []
    step = (price_max - price_min) / buckets
    profile = [{"price_low": round(price_min + i * step, 6),
                "price_high": round(price_min + (i + 1) * step, 6),
                "volume": 0.0, "is_poc": False} for i in range(buckets)]
    for i in range(len(closes)):
        bucket_idx = int((closes[i] - price_min) / step)
        bucket_idx = max(0, min(buckets - 1, bucket_idx))
        profile[bucket_idx]["volume"] += float(volumes[i])
    max_vol = max(b["volume"] for b in profile) if profile else 0
    for b in profile:
        b["volume"] = round(b["volume"], 2)
        b["is_poc"] = (b["volume"] == max_vol and max_vol > 0)
    return profile


@market_data_bp.route("/<int:asset_id>/advanced", methods=["GET"])
@login_required
def get_advanced(asset_id):
    asset     = Asset.query.get_or_404(asset_id)
    timeframe = request.args.get("timeframe", "1h")

    df = market_fetcher.fetch(asset, timeframe, 500)
    if df is None or len(df) < 10:
        return jsonify({"error": "Insufficient data"}), 503

    opens      = df["open"].astype(float).values.tolist()
    highs      = df["high"].astype(float).values.tolist()
    lows       = df["low"].astype(float).values.tolist()
    closes     = df["close"].astype(float).values.tolist()
    volumes    = df["volume"].astype(float).values.tolist() if "volume" in df.columns else [0.0] * len(df)
    timestamps = []
    for ts in df.index:
        try:
            timestamps.append(int(ts.timestamp() * 1000))
        except Exception:
            timestamps.append(0)

    def safe(fn, fallback):
        try:
            return fn()
        except Exception:
            return fallback

    return jsonify({
        "symbol":           asset.symbol,
        "timeframe":        timeframe,
        "fib":              safe(lambda: _compute_fibonacci(highs, lows), {}),
        "liquidity":        safe(lambda: _compute_liquidity(highs, lows, timestamps), {"buy_side": [], "sell_side": []}),
        "fvg":              safe(lambda: _compute_fvg(opens, highs, lows, closes, timestamps), []),
        "order_blocks":     safe(lambda: _compute_order_blocks(opens, highs, lows, closes, timestamps), []),
        "market_structure": safe(lambda: _compute_market_structure(highs, lows, timestamps), {"points": [], "trend": "ranging"}),
        "trend_lines":      safe(lambda: _compute_trend_lines(highs, lows, timestamps), []),
        "vwap":             safe(lambda: _compute_vwap(opens, highs, lows, closes, volumes, timestamps), []),
        "volume_profile":   safe(lambda: _compute_volume_profile(highs, lows, closes, volumes), []),
    }), 200

