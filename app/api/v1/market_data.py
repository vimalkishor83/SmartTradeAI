from flask import Blueprint, request, jsonify
from app.models.asset import Asset
from app.models.market_data import MarketData
from app.extensions import db, cache
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

    df = market_fetcher.fetch(asset, timeframe, 300)
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


@market_data_bp.route("/heatmap", methods=["GET"])
@login_required
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
