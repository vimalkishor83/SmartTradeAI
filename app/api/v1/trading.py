"""
Manual trading endpoints — places/manages real orders on the user's own
Delta Exchange India account. Every route resolves the trading client via
get_configured_client(), which raises a clear DeltaTradingError if no
credentials are configured yet; that error is returned as JSON so the
frontend can show a "Not Connected" state instead of a raw 500.
"""
from flask import Blueprint, request, jsonify
from app.auth.decorators import admin_required
from app.services.data.fetcher import to_delta_symbol
from app.services.trading.delta_trading import get_configured_client, DeltaTradingError

trading_bp = Blueprint("trading", __name__)


def _client_or_error():
    """Returns (client, None) or (None, (response, status))."""
    try:
        return get_configured_client(), None
    except DeltaTradingError as e:
        return None, (jsonify({"error": str(e), "connected": False}), 503)


@trading_bp.route("/status", methods=["GET"])
@admin_required
def status():
    """Whether a Delta Exchange trading connection is configured — the
    frontend calls this first to decide whether to show the trading UI
    or a 'connect your account' prompt."""
    client, err = _client_or_error()
    if err:
        return jsonify({"connected": False}), 200
    try:
        client.get_balances()
        return jsonify({"connected": True}), 200
    except DeltaTradingError as e:
        return jsonify({"connected": False, "error": str(e)}), 200


@trading_bp.route("/balances", methods=["GET"])
@admin_required
def balances():
    client, err = _client_or_error()
    if err:
        return err
    try:
        return jsonify({"balances": client.get_balances()}), 200
    except DeltaTradingError as e:
        return jsonify({"error": str(e)}), e.status_code or 502


@trading_bp.route("/positions", methods=["GET"])
@admin_required
def positions():
    client, err = _client_or_error()
    if err:
        return err
    try:
        return jsonify({"positions": client.get_positions()}), 200
    except DeltaTradingError as e:
        return jsonify({"error": str(e)}), e.status_code or 502


@trading_bp.route("/orders", methods=["GET"])
@admin_required
def open_orders():
    client, err = _client_or_error()
    if err:
        return err
    try:
        return jsonify({"orders": client.get_open_orders()}), 200
    except DeltaTradingError as e:
        return jsonify({"error": str(e)}), e.status_code or 502


@trading_bp.route("/orders/history", methods=["GET"])
@admin_required
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
@admin_required
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
@admin_required
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
