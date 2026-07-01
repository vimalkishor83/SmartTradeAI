from flask import Blueprint, request, jsonify
from app.models.asset import Asset
from app.extensions import db, cache, limiter
from app.auth.decorators import login_required
from app.services.data.fetcher import market_fetcher
from app.services.indicators.calculator import calculate_all_indicators
from app.services.sentiment.engine import calculate_sentiment
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

    df = market_fetcher.fetch(asset, timeframe, 220)
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
    ck     = f"ta_summary_{user.id}_{market}"
    cached = cache.get(ck)
    if cached:
        return jsonify(cached), 200

    # Respect user's asset selection preferences
    prefs = {p.asset_id: p.enabled for p in UserAssetPreference.query.filter_by(user_id=user.id).all()}

    tfs = ["5m", "15m", "30m", "1h", "2h", "4h", "1d"]
    asset_q = Asset.query.filter_by(is_active=True)
    if market != "all":
        asset_q = asset_q.filter_by(market=market)
    all_assets = asset_q.order_by(Asset.market, Asset.symbol).all()
    # If user has saved preferences, filter; otherwise use all
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
                last  = df_price.iloc[-1]
                prev  = df_price.iloc[-2]
                price = float(last["close"])
                chg   = price - float(prev["close"])
                row["price"]      = price
                row["open"]       = float(last["open"])
                row["high"]       = float(last["high"])
                row["low"]        = float(last["low"])
                row["change"]     = round(chg, 6)
                row["change_pct"] = round(chg / float(prev["close"]) * 100, 2) if prev["close"] else 0
                row["volume"]     = float(last.get("volume", 0))
                ts = df_price.index[-1]
                row["time"] = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)
            except Exception:
                pass
        for tf in tfs:
            try:
                df = dfs.get(tf)
                if df is None or len(df) < 52:
                    row["tf"][tf] = None
                    continue
                ind = calculate_all_indicators(df)
                row["tf"][tf] = _compute_ta_rating(ind, float(df["close"].iloc[-1]))
            except Exception:
                row["tf"][tf] = None
        return row

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(8, len(assets))) as ex:
        result = list(ex.map(_process_asset, assets))

    payload = {"assets": result, "timeframes": tfs}
    cache.set(ck, payload, timeout=120)
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
                    "symbol":     asset.symbol,
                    "name":       asset.name,
                    "market":     asset.market,
                    "price":      round(price, 4),
                    "change_pct": round(change, 2),
                })
        except Exception:
            continue
    return jsonify({"heatmap": heatmap}), 200
