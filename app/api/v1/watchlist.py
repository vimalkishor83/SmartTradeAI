from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from app.extensions import db
from app.models.watchlist import Watchlist, WatchlistItem
from app.models.asset import Asset
from app.auth.decorators import login_required

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

    asset = Asset.query.filter_by(symbol=data.get("symbol")).first()
    if not asset:
        return jsonify({"error": "Asset not found"}), 404

    item = WatchlistItem(watchlist_id=wl.id, asset_id=asset.id,
                         alert_price=data.get("alert_price"))
    db.session.add(item)
    db.session.commit()
    return jsonify({"id": item.id, "symbol": asset.symbol}), 201


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
