from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from app.extensions import db, cache
from app.models.watchlist import Watchlist, WatchlistItem
from app.models.asset import Asset
from app.models.signal import Signal
from app.models.user import User
from app.auth.decorators import login_required
from datetime import datetime, timedelta

watchlist_bp = Blueprint("watchlist", __name__)


@watchlist_bp.route("/", methods=["GET"])
@login_required
def get_watchlists():
    user_id = get_jwt_identity()
    lists = Watchlist.query.filter_by(user_id=user_id).all()
    result = []
    for wl in lists:
        items = [{
            "id": i.id, "asset_id": i.asset_id,
            "symbol": i.asset.symbol if i.asset else None,
            "name": i.asset.name if i.asset else None,
            "market": i.asset.market if i.asset else None,
            "alert_price": i.alert_price,
        } for i in wl.items.all()]
        result.append({
            "id": wl.id, "name": wl.name,
            "is_pinned": wl.is_pinned, "items": items,
        })
    return jsonify({"watchlists": result}), 200


@watchlist_bp.route("/", methods=["POST"])
@login_required
def create_watchlist():
    user_id = get_jwt_identity()
    data = request.get_json()
    wl = Watchlist(user_id=user_id, name=data.get("name", "My Watchlist"),
                   description=data.get("description"))
    db.session.add(wl)
    db.session.commit()
    return jsonify({"id": wl.id, "name": wl.name}), 201


@watchlist_bp.route("/<int:wl_id>/items", methods=["POST"])
@login_required
def add_to_watchlist(wl_id):
    user_id = get_jwt_identity()
    wl = Watchlist.query.filter_by(id=wl_id, user_id=user_id).first_or_404()
    data = request.get_json()

    user = User.query.get(int(user_id))
    sub = user.subscription if user else None
    if sub:
        total_items = (WatchlistItem.query.join(Watchlist)
                       .filter(Watchlist.user_id == user_id).count())
        if total_items >= sub.max_watchlist:
            return jsonify({
                "error": f"Watchlist limit reached ({sub.max_watchlist} items on the "
                         f"{sub.name} plan). Remove an item or upgrade your plan.",
            }), 403
        if data.get("alert_price"):
            total_alerts = (WatchlistItem.query.join(Watchlist)
                            .filter(Watchlist.user_id == user_id,
                                    WatchlistItem.alert_price.isnot(None)).count())
            if total_alerts >= sub.max_alerts:
                return jsonify({
                    "error": f"Alert limit reached ({sub.max_alerts} alerts on the "
                             f"{sub.name} plan). Remove an alert or upgrade your plan.",
                }), 403

    asset = Asset.query.filter_by(symbol=data.get("symbol")).first()
    if not asset:
        return jsonify({"error": "Asset not found"}), 404

    alert_price = data.get("alert_price")
    alert_set_at_price = None
    if alert_price:
        # Record the price at the moment the alert is set so the checker can
        # tell whether the current price has actually *crossed* alert_price
        # (moved from one side to the other) rather than just comparing.
        try:
            from app.services.data.fetcher import market_fetcher
            ticker = market_fetcher.fetch_ticker(asset)
            if ticker and ticker.get("price"):
                alert_set_at_price = float(ticker["price"])
        except Exception:
            pass

    item = WatchlistItem(watchlist_id=wl.id, asset_id=asset.id,
                         alert_price=alert_price, alert_set_at_price=alert_set_at_price)
    db.session.add(item)
    db.session.commit()
    return jsonify({"id": item.id, "symbol": asset.symbol}), 201


@watchlist_bp.route("/context", methods=["GET"])
@login_required
def watchlist_context():
    """Rich context view for all watchlist items — price, last signal, MTF confluence."""
    user_id = get_jwt_identity()
    ck = f"watchlist_context_{user_id}"
    cached = cache.get(ck)
    if cached:
        return jsonify(cached), 200

    lists = Watchlist.query.filter_by(user_id=user_id).all()
    # Collect unique (item_id, asset) pairs across all watchlists
    seen_asset_ids = set()
    items_raw = []
    for wl in lists:
        for item in wl.items.all():
            if item.asset_id not in seen_asset_ids and item.asset:
                seen_asset_ids.add(item.asset_id)
                items_raw.append(item)

    from app.services.data.fetcher import market_fetcher
    from app.services.indicators.calculator import calculate_all_indicators

    def _mtf_confluence(asset):
        """Return buy_count, sell_count, hold_count across 1h/4h/1d."""
        tfs = ["1h", "4h", "1d"]
        buy_c = sell_c = hold_c = 0
        try:
            dfs = market_fetcher.fetch_many([asset], tfs, limit=200).get(asset.symbol, {})
            for tf in tfs:
                df = dfs.get(tf)
                if df is None or len(df) < 52:
                    continue
                ind   = calculate_all_indicators(df)
                close = float(df["close"].iloc[-1])
                rating = _compute_mtf_rating(ind, close)
                if rating:
                    if rating["signal_type"] == "BUY":  buy_c  += 1
                    elif rating["signal_type"] == "SELL": sell_c += 1
                    else:                                 hold_c += 1
        except Exception:
            pass
        return buy_c, sell_c, hold_c

    def _compute_mtf_rating(ind, close):
        buy = sell = neutral = 0
        def vote(v):
            nonlocal buy, sell, neutral
            if v == "buy":    buy     += 1
            elif v == "sell": sell    += 1
            else:             neutral += 1

        rsi = ind.get("rsi")
        if rsi is not None:
            vote("buy" if rsi < 30 else "sell" if rsi > 70 else "neutral")
        macd, macd_sig = ind.get("macd"), ind.get("macd_signal")
        if macd is not None and macd_sig is not None:
            vote("buy" if macd > macd_sig else "sell" if macd < macd_sig else "neutral")
        for ma_key in ["ema20", "ema50", "ema200", "sma50"]:
            ma = ind.get(ma_key)
            if ma:
                vote("buy" if close > ma else "sell")
        total = buy + sell + neutral
        if not total:
            return None
        score = (buy - sell) / total
        if score >= 0.4:    sig = "BUY"
        elif score <= -0.4: sig = "SELL"
        else:               sig = "HOLD"
        return {"signal_type": sig, "confidence": round(max(buy, sell) / total * 100)}

    result = []
    now_utc = datetime.utcnow()

    for item in items_raw:
        asset = item.asset
        entry = {
            "asset_id":  asset.id,
            "symbol":    asset.symbol,
            "name":      asset.name,
            "market":    asset.market,
            "alert_price": item.alert_price,
            "current_price": None,
            "change_pct": None,
            "last_signal_type": None,
            "last_signal_tf": None,
            "last_signal_time": None,
            "last_signal_confidence": None,
            "last_signal_stop_loss": None,
            "confluence_score": None,
            "distance_to_alert_pct": None,
        }

        # Current price
        try:
            ticker = market_fetcher.fetch_ticker(asset)
            if ticker:
                entry["current_price"] = ticker.get("price")
                entry["change_pct"]    = ticker.get("change_pct")
        except Exception:
            pass

        # Last active signal
        try:
            sig = (Signal.query
                   .filter_by(asset_id=asset.id, status="active")
                   .order_by(Signal.generated_at.desc())
                   .first())
            if sig:
                entry["last_signal_type"]       = sig.signal_type
                entry["last_signal_tf"]         = sig.timeframe
                entry["last_signal_time"]       = sig.generated_at.isoformat() if sig.generated_at else None
                entry["last_signal_confidence"] = sig.confidence_score
                entry["last_signal_stop_loss"]  = sig.stop_loss
        except Exception:
            pass

        # MTF confluence
        try:
            buy_c, sell_c, hold_c = _mtf_confluence(asset)
            total_tf = buy_c + sell_c + hold_c
            if total_tf:
                if buy_c >= sell_c:
                    entry["confluence_score"] = f"{buy_c}/{total_tf} BUY"
                else:
                    entry["confluence_score"] = f"{sell_c}/{total_tf} SELL"
        except Exception:
            pass

        # Distance to alert price
        if entry["current_price"] and item.alert_price and item.alert_price > 0:
            dist = (item.alert_price - entry["current_price"]) / entry["current_price"] * 100
            entry["distance_to_alert_pct"] = round(dist, 2)

        result.append(entry)

    payload = {"context": result}
    cache.set(ck, payload, timeout=60)
    return jsonify(payload), 200


@watchlist_bp.route("/items/<int:item_id>", methods=["DELETE"])
@login_required
def remove_from_watchlist(item_id):
    user_id = get_jwt_identity()
    item = WatchlistItem.query.join(Watchlist).filter(
        WatchlistItem.id == item_id, Watchlist.user_id == user_id
    ).first_or_404()
    db.session.delete(item)
    db.session.commit()
    return jsonify({"message": "Removed"}), 200


@watchlist_bp.route("/<int:wl_id>", methods=["DELETE"])
@login_required
def delete_watchlist(wl_id):
    user_id = get_jwt_identity()
    wl = Watchlist.query.filter_by(id=wl_id, user_id=user_id).first_or_404()
    db.session.delete(wl)
    db.session.commit()
    return jsonify({"message": "Watchlist deleted"}), 200
