from flask import Blueprint, request, jsonify
from app.models.asset import Asset
from app.extensions import db, cache, limiter
from app.auth.decorators import login_required, admin_required
from app.services.data.fetcher import market_fetcher

assets_bp = Blueprint("assets", __name__)


@assets_bp.route("/", methods=["GET"])
@login_required
def list_assets():
    market = request.args.get("market")
    cache_key = f"assets_list_{market or 'all'}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached), 200

    query = Asset.query.filter_by(is_active=True)
    if market:
        query = query.filter_by(market=market)
    assets = query.order_by(Asset.market, Asset.symbol).all()
    result = {"assets": [a.to_dict() for a in assets]}
    cache.set(cache_key, result, timeout=300)
    return jsonify(result), 200


@assets_bp.route("/<int:asset_id>", methods=["GET"])
@login_required
def get_asset(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    return jsonify(asset.to_dict()), 200


@assets_bp.route("/<int:asset_id>/ticker", methods=["GET"])
@login_required
@limiter.exempt
def get_ticker(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    ticker = market_fetcher.fetch_ticker(asset)
    if not ticker:
        return jsonify({"error": "Ticker data unavailable"}), 503
    return jsonify(ticker), 200


@assets_bp.route("/", methods=["POST"])
@admin_required
def create_asset():
    data = request.get_json()
    required = ["symbol", "name", "market"]
    if not all(k in data for k in required):
        return jsonify({"error": "Missing required fields"}), 400
    asset = Asset(**{k: data[k] for k in data if hasattr(Asset, k)})
    db.session.add(asset)
    db.session.commit()
    cache.delete("assets_list")
    return jsonify(asset.to_dict()), 201


@assets_bp.route("/<int:asset_id>", methods=["PUT"])
@admin_required
def update_asset(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    data = request.get_json()
    for k, v in data.items():
        if hasattr(asset, k):
            setattr(asset, k, v)
    db.session.commit()
    cache.delete("assets_list")
    return jsonify(asset.to_dict()), 200


@assets_bp.route("/<int:asset_id>", methods=["DELETE"])
@admin_required
def delete_asset(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    # Soft delete — keeps historical signals intact
    asset.is_active = False
    db.session.commit()
    for mk in Asset.MARKETS + ["all"]:
        cache.delete(f"assets_list_{mk}")
    return jsonify({"message": f"{asset.symbol} removed from platform"}), 200


@assets_bp.route("/markets", methods=["GET"])
@login_required
def get_markets():
    return jsonify({"markets": Asset.MARKETS}), 200


@assets_bp.route("/search", methods=["GET"])
@admin_required
def search_asset():
    """Search Yahoo Finance for any symbol by keyword/name."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"results": []}), 200

    try:
        import requests as _req
        url = "https://query1.finance.yahoo.com/v1/finance/search"
        params = {"q": q, "quotesCount": 15, "newsCount": 0, "enableFuzzyQuery": True, "enableNavLinks": False}
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = _req.get(url, params=params, headers=headers, timeout=8)
        resp.raise_for_status()
        quotes = resp.json().get("quotes", [])
    except Exception as e:
        return jsonify({"error": str(e), "results": []}), 200

    results = []
    for item in quotes:
        sym  = item.get("symbol", "")
        name = item.get("longname") or item.get("shortname") or sym
        exch = item.get("exchange", "")
        typ  = item.get("quoteType", "")
        if sym:
            results.append({"symbol": sym, "name": name, "exchange": exch, "type": typ})

    return jsonify({"results": results}), 200


@assets_bp.route("/add-from-search", methods=["POST"])
@admin_required
def add_from_search():
    """Add an asset found via search to the platform."""
    data = request.get_json() or {}
    symbol   = (data.get("symbol") or "").strip().upper()
    name     = (data.get("name") or "").strip()
    exchange = (data.get("exchange") or "").strip()
    market   = (data.get("market") or "index").strip()

    if not symbol or not name:
        return jsonify({"error": "symbol and name are required"}), 400

    existing = Asset.query.filter_by(symbol=symbol).first()
    if existing:
        return jsonify({"error": f"{symbol} already exists", "asset": existing.to_dict()}), 409

    asset = Asset(
        symbol=symbol,
        name=name,
        market=market,
        exchange=exchange,
        data_source="yahoo",
        is_active=True,
    )
    db.session.add(asset)
    db.session.commit()
    # clear asset list cache for all markets
    for mk in Asset.MARKETS + ["all"]:
        cache.delete(f"assets_list_{mk}")
    return jsonify({"message": f"{symbol} added successfully", "asset": asset.to_dict()}), 201
