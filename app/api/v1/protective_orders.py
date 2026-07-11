"""
User-configured stop-loss / take-profit / trailing-stop watches on the
user's own Portfolio holdings. Monitoring runs in a background job
(app/tasks/protective_order_tasks.py); this module is only the CRUD API.

Safety defaults: creating a ProtectiveOrder defaults to auto_execute=False
(monitor + notify only) and is_dry_run=True (even if auto_execute is later
turned on, no real order is sent while dry_run stays True). A user must
explicitly opt in twice -- flip auto_execute on AND turn dry_run off -- for
this feature to ever place a real order on their connected broker account.
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from app.extensions import db
from app.models.portfolio import Portfolio, PortfolioItem
from app.models.protective_order import ProtectiveOrder
from app.auth.decorators import login_required, approved_required

protective_orders_bp = Blueprint("protective_orders", __name__)


def _owned_item_or_error(item_id, user_id):
    item = PortfolioItem.query.join(Portfolio).filter(
        PortfolioItem.id == item_id, Portfolio.user_id == user_id
    ).first()
    if not item:
        return None, (jsonify({"error": "Portfolio position not found"}), 404)
    return item, None


@protective_orders_bp.route("/", methods=["GET"])
@login_required
def list_protective_orders():
    user_id = get_jwt_identity()
    orders = ProtectiveOrder.query.filter_by(user_id=user_id).order_by(ProtectiveOrder.created_at.desc()).all()
    return jsonify({"protective_orders": [o.to_dict() for o in orders]}), 200


@protective_orders_bp.route("/", methods=["POST"])
@approved_required
def create_protective_order():
    """Body: {portfolio_item_id, side, stop_loss?, take_profit?,
    trailing_enabled?, trailing_distance_pct?, auto_execute?, is_dry_run?}

    auto_execute defaults False; is_dry_run defaults True regardless of
    what's passed for auto_execute — a client wanting live execution must
    explicitly pass is_dry_run:false in a separate, deliberate step (see
    the PATCH route), not bundle it into creation.
    """
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    item_id = data.get("portfolio_item_id")
    if not item_id:
        return jsonify({"error": "portfolio_item_id is required"}), 400
    item, err = _owned_item_or_error(item_id, user_id)
    if err:
        return err

    side = (data.get("side") or "long").strip().lower()
    if side not in ("long", "short"):
        return jsonify({"error": "side must be 'long' or 'short'"}), 400

    stop_loss = data.get("stop_loss")
    take_profit = data.get("take_profit")
    trailing_enabled = bool(data.get("trailing_enabled", False))
    trailing_distance_pct = data.get("trailing_distance_pct")

    if trailing_enabled and not trailing_distance_pct:
        return jsonify({"error": "trailing_distance_pct is required when trailing_enabled is true"}), 400
    if trailing_distance_pct is not None:
        try:
            trailing_distance_pct = float(trailing_distance_pct)
        except (TypeError, ValueError):
            return jsonify({"error": "trailing_distance_pct must be a number"}), 400
        if trailing_distance_pct <= 0:
            return jsonify({"error": "trailing_distance_pct must be greater than zero"}), 400

    if stop_loss is None and take_profit is None and not trailing_enabled:
        return jsonify({"error": "at least one of stop_loss, take_profit, or trailing_enabled is required"}), 400

    order = ProtectiveOrder(
        user_id=user_id,
        portfolio_item_id=item.id,
        asset_id=item.asset_id,
        side=side,
        stop_loss=float(stop_loss) if stop_loss is not None else None,
        take_profit=float(take_profit) if take_profit is not None else None,
        trailing_enabled=trailing_enabled,
        trailing_distance_pct=trailing_distance_pct,
        high_water_mark=item.current_price or item.buy_price,
        auto_execute=bool(data.get("auto_execute", False)),
        is_dry_run=True,   # always starts safe — flip off explicitly via PATCH
        status="active",
    )
    db.session.add(order)
    db.session.commit()
    return jsonify(order.to_dict()), 201


@protective_orders_bp.route("/<int:order_id>", methods=["PATCH"])
@approved_required
def update_protective_order(order_id):
    """Only field allowed here that arms real trading is is_dry_run=false
    combined with auto_execute=true — both must be explicitly set by the
    caller in the same or a prior request; neither flips on by default."""
    user_id = int(get_jwt_identity())
    order = ProtectiveOrder.query.filter_by(id=order_id, user_id=user_id).first()
    if not order:
        return jsonify({"error": "Protective order not found"}), 404
    if order.status != "active":
        return jsonify({"error": f"Cannot edit a protective order in status '{order.status}'"}), 400

    data = request.get_json() or {}
    for field in ("stop_loss", "take_profit", "trailing_distance_pct"):
        if field in data and data[field] is not None:
            try:
                setattr(order, field, float(data[field]))
            except (TypeError, ValueError):
                return jsonify({"error": f"{field} must be a number"}), 400
    if "trailing_enabled" in data:
        order.trailing_enabled = bool(data["trailing_enabled"])
    if "auto_execute" in data:
        order.auto_execute = bool(data["auto_execute"])
    if "is_dry_run" in data:
        order.is_dry_run = bool(data["is_dry_run"])

    db.session.commit()
    return jsonify(order.to_dict()), 200


@protective_orders_bp.route("/<int:order_id>", methods=["DELETE"])
@login_required
def cancel_protective_order(order_id):
    user_id = get_jwt_identity()
    order = ProtectiveOrder.query.filter_by(id=order_id, user_id=user_id).first()
    if not order:
        return jsonify({"error": "Protective order not found"}), 404
    order.status = "cancelled"
    db.session.commit()
    return jsonify({"message": "Protective order cancelled"}), 200
