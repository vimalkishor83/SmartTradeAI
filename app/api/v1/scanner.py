from flask import Blueprint, request, jsonify
from app.models.asset import Asset
from app.auth.decorators import login_required
from app.services.data.fetcher import market_fetcher
from app.services.indicators.calculator import calculate_all_indicators
from app.extensions import cache

scanner_bp = Blueprint("scanner", __name__)

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
    data = request.get_json()
    filters = data.get("filters", ["strong_buy"])
    market = data.get("market")
    timeframe = data.get("timeframe", "1d")

    query = Asset.query.filter_by(is_active=True)
    if market:
        query = query.filter_by(market=market)
    assets = query.all()

    results = []
    for asset in assets:
        df = market_fetcher.fetch(asset, timeframe, 220)
        if df is None or len(df) < 60:
            continue
        try:
            ind = calculate_all_indicators(df)
            match = _apply_filters(df, ind, filters)
            if match:
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

    return jsonify({"results": results, "count": len(results)}), 200


def _apply_filters(df, ind, filters) -> list:
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
        "gap_up": open_ > prev_close * 1.01,
        "gap_down": open_ < prev_close * 0.99,
        "rsi_oversold": rsi < 30,
        "rsi_overbought": rsi > 70,
    }

    for f in filters:
        if checks.get(f, False):
            matched.append(f)

    return matched
