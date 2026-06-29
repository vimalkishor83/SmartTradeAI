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


@assets_bp.route("/markets", methods=["GET"])
@login_required
def get_markets():
    return jsonify({"markets": Asset.MARKETS}), 200
