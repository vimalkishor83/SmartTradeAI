"""
Multi-asset comparison — side-by-side view for 2-5 assets: normalized
price performance over a chosen lookback, current TA rating, AI
prediction confidence, and key stats (change %, volume). No comparison
view existed anywhere in the app before this — every page (asset detail,
TA Summary, MTF Analysis) is single-asset or a big table, not a focused
"pick between these similar setups" view a swing trader commonly wants.
"""
from flask import Blueprint, request, jsonify
from app.models.asset import Asset
from app.auth.decorators import login_required
from app.extensions import cache

comparison_bp = Blueprint("comparison", __name__)

_MAX_COMPARE = 5


@comparison_bp.route("/", methods=["GET"])
@login_required
def compare_assets():
    """
    ?symbols=BTCUSDT,ETHUSDT,SOLUSDT&timeframe=1h&lookback=100

    Returns per-asset: normalized performance series (all series rebased
    to 100 at the first common bar, so relative performance is directly
    comparable regardless of absolute price), current TA rating, AI
    prediction, and headline stats.
    """
    symbols_param = request.args.get("symbols", "")
    symbols = [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
    if len(symbols) < 2:
        return jsonify({"error": "Provide at least 2 symbols, comma-separated (e.g. ?symbols=BTCUSDT,ETHUSDT)"}), 400
    if len(symbols) > _MAX_COMPARE:
        return jsonify({"error": f"Maximum {_MAX_COMPARE} assets can be compared at once"}), 400

    timeframe = request.args.get("timeframe", "1h")
    try:
        lookback = max(20, min(500, int(request.args.get("lookback", 100))))
    except (TypeError, ValueError):
        lookback = 100

    ck = f"compare_{'_'.join(sorted(symbols))}_{timeframe}_{lookback}"
    cached = cache.get(ck)
    if cached:
        return jsonify(cached), 200

    assets = Asset.query.filter(Asset.symbol.in_(symbols), Asset.is_active == True).all()
    assets_by_symbol = {a.symbol: a for a in assets}
    missing = [s for s in symbols if s not in assets_by_symbol]
    if missing:
        return jsonify({"error": f"Unknown or inactive symbol(s): {', '.join(missing)}"}), 404

    from app.services.data.fetcher import market_fetcher
    from app.services.indicators.calculator import calculate_all_indicators
    from app.api.v1.market_data import _compute_ta_rating

    ordered_assets = [assets_by_symbol[s] for s in symbols]
    data = market_fetcher.fetch_many(ordered_assets, [timeframe], limit=lookback)

    results = []
    for asset in ordered_assets:
        dfs = data.get(asset.symbol, {})
        df = dfs.get(timeframe)
        entry = {
            "symbol": asset.symbol, "name": asset.name, "market": asset.market,
            "performance": [], "change_pct": None, "volume": None,
            "ta_rating": None, "ai_prediction": None,
        }
        if df is None or len(df) < 2:
            results.append(entry)
            continue

        closes = df["close"].astype(float)
        base = float(closes.iloc[0])
        # Rebase every series to 100 at the first common bar so relative
        # performance is directly comparable across assets with very
        # different absolute price levels (e.g. BTCUSDT ~64000 vs a
        # sub-$1 altcoin) — an overlay chart of raw prices would be
        # useless for exactly the assets a user most wants to compare.
        if base:
            entry["performance"] = [
                {"time": int(t.timestamp()) if hasattr(t, "timestamp") else i,
                 "value": round(float(c) / base * 100, 3)}
                for i, (t, c) in enumerate(zip(df.index, closes))
            ]
            entry["change_pct"] = round((float(closes.iloc[-1]) - base) / base * 100, 2)

        entry["volume"] = float(df["volume"].iloc[-1]) if "volume" in df.columns else None

        try:
            ind = calculate_all_indicators(df, light=True)
            entry["ta_rating"] = _compute_ta_rating(ind, float(closes.iloc[-1]))
        except Exception:
            pass

        try:
            from app.services.ai.predictor import ai_predictor
            pred = ai_predictor.predict(df, asset.symbol, timeframe)
            entry["ai_prediction"] = {
                "direction": pred.get("predicted_direction"),
                "confidence": pred.get("confidence"),
            }
        except Exception:
            pass

        results.append(entry)

    payload = {"timeframe": timeframe, "lookback": lookback, "assets": results}
    cache.set(ck, payload, timeout=60)
    return jsonify(payload), 200
