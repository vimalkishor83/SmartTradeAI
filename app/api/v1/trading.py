"""
Manual trading endpoints — places/manages real orders on the CURRENT USER'S
OWN Delta Exchange India account. Every route resolves the trading client via
get_configured_client(user_id), which raises a clear DeltaTradingError if
that user hasn't connected credentials yet; that error is returned as JSON
so the frontend can show a "Not Connected" state instead of a raw 500.

Non-custodial by design: trading is gated on @approved_required (not just
@login_required) since it moves real money — a self-registered account
still pending admin review cannot place live orders even if they've
connected a broker key.
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from app.extensions import db
from app.auth.decorators import login_required, approved_required
from app.services.data.fetcher import to_delta_symbol
from app.services.trading.delta_trading import get_configured_client, DeltaTradingError

trading_bp = Blueprint("trading", __name__)


def _client_or_error():
    """Returns (client, None) or (None, (response, status)) for the current user."""
    user_id = int(get_jwt_identity())
    try:
        return get_configured_client(user_id), None
    except DeltaTradingError as e:
        return None, (jsonify({"error": str(e), "connected": False}), 503)


# ── Broker connection management (per-user) ────────────────────────────────

@trading_bp.route("/broker/status", methods=["GET"])
@login_required
def broker_status():
    """Whether the CURRENT user has a Delta Exchange connection configured."""
    from app.models.api_config import UserBrokerCredential
    user_id = get_jwt_identity()
    cred = UserBrokerCredential.query.filter_by(
        user_id=user_id, provider="delta_exchange"
    ).first()
    if not cred:
        return jsonify({"connected": False}), 200
    return jsonify({"connected": cred.is_active, **cred.to_dict()}), 200


@trading_bp.route("/broker/connect", methods=["POST"])
@approved_required
def broker_connect():
    """Save (or replace) the current user's own Delta Exchange API key/secret."""
    from app.models.api_config import UserBrokerCredential
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    api_key = (data.get("api_key") or "").strip()
    api_secret = (data.get("api_secret") or "").strip()

    if not api_key or not api_secret:
        return jsonify({"error": "api_key and api_secret are required"}), 400

    cred = UserBrokerCredential.query.filter_by(
        user_id=user_id, provider="delta_exchange"
    ).first()
    if not cred:
        cred = UserBrokerCredential(user_id=user_id, provider="delta_exchange")
        db.session.add(cred)

    cred.set_api_key(api_key)
    cred.set_api_secret(api_secret)
    cred.is_active = True
    cred.connection_status = "unknown"
    db.session.commit()

    return jsonify({"message": "Broker connected", **cred.to_dict()}), 200


@trading_bp.route("/broker/disconnect", methods=["POST"])
@login_required
def broker_disconnect():
    from app.models.api_config import UserBrokerCredential
    user_id = get_jwt_identity()
    cred = UserBrokerCredential.query.filter_by(
        user_id=user_id, provider="delta_exchange"
    ).first()
    if cred:
        db.session.delete(cred)
        db.session.commit()
    return jsonify({"message": "Broker disconnected"}), 200


# ── Trading (requires an approved account with a connected broker) ─────────

@trading_bp.route("/status", methods=["GET"])
@approved_required
def status():
    """Whether the trading connection actually works — the frontend calls
    this first to decide whether to show the trading UI or a 'connect your
    account' prompt."""
    client, err = _client_or_error()
    if err:
        return jsonify({"connected": False}), 200
    try:
        client.get_balances()
        return jsonify({"connected": True}), 200
    except DeltaTradingError as e:
        return jsonify({"connected": False, "error": str(e)}), 200


@trading_bp.route("/balances", methods=["GET"])
@approved_required
def balances():
    client, err = _client_or_error()
    if err:
        return err
    try:
        return jsonify({"balances": client.get_balances()}), 200
    except DeltaTradingError as e:
        return jsonify({"error": str(e)}), e.status_code or 502


@trading_bp.route("/positions", methods=["GET"])
@approved_required
def positions():
    client, err = _client_or_error()
    if err:
        return err
    try:
        return jsonify({"positions": client.get_positions()}), 200
    except DeltaTradingError as e:
        return jsonify({"error": str(e)}), e.status_code or 502


@trading_bp.route("/orders", methods=["GET"])
@approved_required
def open_orders():
    client, err = _client_or_error()
    if err:
        return err
    try:
        return jsonify({"orders": client.get_open_orders()}), 200
    except DeltaTradingError as e:
        return jsonify({"error": str(e)}), e.status_code or 502


@trading_bp.route("/orders/history", methods=["GET"])
@approved_required
def order_history():
    client, err = _client_or_error()
    if err:
        return err
    try:
        after = request.args.get("after")
        return jsonify({"orders": client.get_order_history(after=after)}), 200
    except DeltaTradingError as e:
        return jsonify({"error": str(e)}), e.status_code or 502


@trading_bp.route("/orders", methods=["POST"])
@approved_required
def place_order():
    client, err = _client_or_error()
    if err:
        return err

    data = request.get_json() or {}
    our_symbol = (data.get("symbol") or "").strip().upper()
    side = (data.get("side") or "").strip().lower()
    size = data.get("size")
    order_type = (data.get("order_type") or "limit_order").strip()
    limit_price = data.get("limit_price")
    stop_price = data.get("stop_price")
    reduce_only = bool(data.get("reduce_only", False))
    leverage = data.get("leverage")

    if not our_symbol or not side or not size:
        return jsonify({"error": "symbol, side and size are required"}), 400

    delta_symbol = to_delta_symbol(our_symbol)
    if not delta_symbol:
        return jsonify({"error": f"{our_symbol} is not a tradeable Delta Exchange symbol"}), 400

    try:
        product_id = client.get_product_id(delta_symbol)
        if leverage:
            client.set_leverage(product_id, int(leverage))
        result = client.place_order(
            product_id=product_id, side=side, size=int(size), order_type=order_type,
            limit_price=limit_price, stop_price=stop_price, reduce_only=reduce_only,
        )
        return jsonify({"order": result}), 201
    except DeltaTradingError as e:
        return jsonify({"error": str(e)}), e.status_code or 400


@trading_bp.route("/orders/<int:order_id>", methods=["DELETE"])
@approved_required
def cancel_order(order_id):
    client, err = _client_or_error()
    if err:
        return err
    product_id = request.args.get("product_id")
    if not product_id:
        return jsonify({"error": "product_id is required to cancel an order"}), 400
    try:
        result = client.cancel_order(order_id, int(product_id))
        return jsonify({"order": result}), 200
    except DeltaTradingError as e:
        return jsonify({"error": str(e)}), e.status_code or 400
