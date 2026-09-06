"""
Manual trading endpoints — places/manages real orders on the CURRENT USER'S
OWN Delta Exchange India account. Every trading route resolves the client via
get_configured_client(user_id), which raises a clear DeltaTradingError if
that user hasn't connected Delta credentials yet; that error is returned as
JSON so the frontend can show a "Not Connected" state instead of a raw 500.
(Only Delta has a live trading client wired up today — see broker_registry.py
for the full multi-broker connection framework, which lets a user store
encrypted credentials for ~18 brokers even before each one's trading client
is built.)

Non-custodial by design: trading is gated on @approved_required (not just
@login_required) since it moves real money — a self-registered account
still pending admin review cannot place live orders even if they've
connected a broker key.
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from decimal import Decimal, InvalidOperation
import re
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.auth.decorators import login_required, approved_required, subscription_feature_required
from app.services.data.fetcher import to_delta_symbol
from app.services.trading.delta_trading import get_configured_client, DeltaTradingError
from app.services.trading.broker_registry import get_broker, list_brokers, required_fields

trading_bp = Blueprint("trading", __name__)

MAX_ORDER_SIZE = 10_000_000
MAX_LEVERAGE = 200
MAX_PRICE = Decimal("1000000000000")
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,40}$")
_MAX_CREDENTIAL_LENGTH = 1024


def _positive_int(value, field_name, maximum=None):
    """Parse a whole positive integer without accepting floats or booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{field_name} must be a whole number")
    text = str(value).strip()
    if not re.fullmatch(r"[1-9]\d*", text):
        raise ValueError(f"{field_name} must be a whole number greater than zero")
    number = int(text)
    if maximum is not None and number > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}")
    return number


def _positive_price(value, field_name, required=False):
    """Return a finite positive decimal string suitable for the broker API."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError(f"{field_name} must be a positive number")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field_name} must be a positive number")
    if not number.is_finite() or number <= 0 or number > MAX_PRICE:
        raise ValueError(f"{field_name} must be between zero and {MAX_PRICE}")
    return format(number, "f")


def _parse_bool(value, field_name):
    """Parse JSON booleans without Python's unsafe bool("false") coercion."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    raise ValueError(f"{field_name} must be a boolean")


def _credential_text(value, field_name):
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} is required")
    if len(value) > _MAX_CREDENTIAL_LENGTH:
        raise ValueError(f"{field_name} must be {_MAX_CREDENTIAL_LENGTH} characters or fewer")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{field_name} contains unsupported control characters")
    return value


def _client_or_error():
    """Returns (client, None) or (None, (response, status)) for the current user."""
    user_id = int(get_jwt_identity())
    try:
        return get_configured_client(user_id), None
    except DeltaTradingError as e:
        return None, (jsonify({"error": str(e), "connected": False}), 503)


def _audit(user_id, action, provider):
    """Every broker connect/disconnect/test action is logged — these touch
    real trading credentials, so a visible audit trail (who connected what,
    when, from where) matters even though the credential itself is never
    exposed in the log."""
    from app.models.audit import AuditLog
    try:
        AuditLog.record(
            user_id, action, resource="broker_credential", resource_id=provider,
            ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent", ""),
        )
    except Exception:
        pass


def _audit_trade(user_id, action, resource_id=None, status="success", details=None):
    """Record an execution event without allowing audit I/O to affect trading."""
    from app.models.audit import AuditLog
    try:
        AuditLog.record(
            user_id, action, resource="trading_order",
            resource_id=str(resource_id) if resource_id is not None else None,
            status=status, details=details or {},
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent", ""),
        )
    except Exception:
        pass


# ── Broker catalog (which providers exist, what fields each needs) ─────────

@trading_bp.route("/brokers", methods=["GET"])
@login_required
def brokers_catalog():
    """Full list of supported brokers with their category, auth field
    requirements, and whether live trading is actually wired up yet — the
    frontend uses this to render the "Connect a broker" picker and the
    right form fields per broker without hardcoding broker knowledge."""
    return jsonify({"brokers": list_brokers()}), 200


# ── Broker connection management (per-user, MULTIPLE brokers) ──────────────

@trading_bp.route("/broker/connections", methods=["GET"])
@login_required
def broker_connections():
    """All of the CURRENT user's connected brokers (not just Delta) —
    a user can have Delta + Binance + Zerodha connected simultaneously,
    one row per (user, provider)."""
    from app.models.api_config import UserBrokerCredential
    user_id = get_jwt_identity()
    creds = UserBrokerCredential.query.filter_by(user_id=user_id).all()
    return jsonify({"connections": [c.to_dict() for c in creds]}), 200


@trading_bp.route("/broker/status", methods=["GET"])
@login_required
def broker_status():
    """Backward-compatible single-broker status check (Delta specifically)
    — kept for the existing Trading page, which only trades via Delta."""
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
@subscription_feature_required("broker_connect_enabled")
def broker_connect():
    """Save (or replace) the current user's own credentials for ANY
    supported broker — provider is now a request field, not hardcoded."""
    from app.models.api_config import UserBrokerCredential
    user_id = get_jwt_identity()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400
    provider_raw = data.get("provider") or "delta_exchange"
    if not isinstance(provider_raw, str):
        return jsonify({"error": "provider must be a string"}), 400
    provider = provider_raw.strip().lower()

    meta = get_broker(provider)
    if not meta:
        return jsonify({"error": f"Unknown broker '{provider}'"}), 400
    if meta["auth_type"] == "oauth":
        return jsonify({
            "error": f"{meta['label']} uses a browser login flow, not a key/secret — not yet supported.",
        }), 400

    needed = required_fields(provider)
    values = {}
    try:
        for field in needed:
            values[field] = _credential_text(data.get(field), field)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    cred = UserBrokerCredential.query.filter_by(user_id=user_id, provider=provider).first()
    if not cred:
        cred = UserBrokerCredential(user_id=user_id, provider=provider)
        db.session.add(cred)

    if "api_key" in values:
        cred.set_api_key(values["api_key"])
    if "api_secret" in values:
        cred.set_api_secret(values["api_secret"])
    if "passphrase" in values:
        cred.set_passphrase(values["passphrase"])
    cred.is_active = True
    cred.connection_status = "unknown"
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "This broker connection was updated by another request; please retry"}), 409

    _audit(user_id, "broker_connected", provider)
    return jsonify({"message": f"{meta['label']} connected", **cred.to_dict()}), 200


@trading_bp.route("/broker/disconnect", methods=["POST"])
@login_required
def broker_disconnect():
    """Disconnect a specific broker — provider comes from the request body
    (defaults to delta_exchange for backward compatibility with the
    existing Trading page's disconnect button)."""
    from app.models.api_config import UserBrokerCredential
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400
    provider_raw = data.get("provider") or "delta_exchange"
    if not isinstance(provider_raw, str):
        return jsonify({"error": "provider must be a string"}), 400
    provider = provider_raw.strip().lower()

    cred = UserBrokerCredential.query.filter_by(user_id=user_id, provider=provider).first()
    if cred:
        db.session.delete(cred)
        db.session.commit()
        _audit(user_id, "broker_disconnected", provider)
    return jsonify({"message": "Broker disconnected"}), 200


@trading_bp.route("/broker/test", methods=["POST"])
@login_required
def broker_test():
    """Verify a connected broker's credentials actually work. Only
    meaningful for brokers with trading_enabled=True (a real client wired
    up) — others return a clear "not yet supported" response rather than
    silently pretending to test something with no implementation."""
    from app.models.api_config import UserBrokerCredential
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400
    provider_raw = data.get("provider") or "delta_exchange"
    if not isinstance(provider_raw, str):
        return jsonify({"error": "provider must be a string"}), 400
    provider = provider_raw.strip().lower()

    meta = get_broker(provider)
    if not meta:
        return jsonify({"error": f"Unknown broker '{provider}'"}), 400

    cred = UserBrokerCredential.query.filter_by(user_id=user_id, provider=provider).first()
    if not cred:
        return jsonify({"error": "Not connected"}), 404

    if not meta.get("trading_enabled"):
        return jsonify({
            "tested": False,
            "message": f"{meta['label']} credentials are saved and encrypted, but live trading isn't wired up for this broker yet.",
        }), 200

    if provider == "delta_exchange":
        try:
            client = get_configured_client(int(user_id))
            client.get_balances()
            cred.connection_status = "ok"
            cred.last_error = None
            db.session.commit()
            _audit(user_id, "broker_test_ok", provider)
            return jsonify({"tested": True, "connected": True}), 200
        except DeltaTradingError as e:
            cred.connection_status = "error"
            cred.last_error = str(e)
            db.session.commit()
            _audit(user_id, "broker_test_failed", provider)
            return jsonify({"tested": True, "connected": False, "error": str(e)}), 200

    return jsonify({"tested": False, "message": "No test implemented for this broker yet."}), 200


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
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400

    symbol_raw = data.get("symbol")
    side_raw = data.get("side")
    order_type_raw = data.get("order_type", "limit_order")
    if not isinstance(symbol_raw, str) or not isinstance(side_raw, str) or not isinstance(order_type_raw, str):
        return jsonify({"error": "symbol, side and order_type must be strings"}), 400
    our_symbol = symbol_raw.strip().upper()
    side = side_raw.strip().lower()
    order_type = order_type_raw.strip()

    if not our_symbol or not _SYMBOL_RE.fullmatch(our_symbol):
        return jsonify({"error": "symbol must contain only letters and numbers"}), 400
    try:
        reduce_only = _parse_bool(data.get("reduce_only", False), "reduce_only")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if not side:
        return jsonify({"error": "symbol, side and size are required"}), 400

    if side not in ("buy", "sell"):
        return jsonify({"error": "side must be 'buy' or 'sell'"}), 400

    if order_type not in ("limit_order", "market_order"):
        return jsonify({"error": "order_type must be 'limit_order' or 'market_order'"}), 400

    try:
        size_int = _positive_int(data.get("size"), "size", MAX_ORDER_SIZE)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        limit_price = _positive_price(
            data.get("limit_price"), "limit_price", required=order_type == "limit_order"
        )
        stop_price = _positive_price(data.get("stop_price"), "stop_price")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    leverage_int = None
    leverage = data.get("leverage")
    if leverage is not None and leverage != "":
        try:
            leverage_int = _positive_int(leverage, "leverage", MAX_LEVERAGE)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    client, err = _client_or_error()
    if err:
        return err

    delta_symbol = to_delta_symbol(our_symbol)
    if not delta_symbol:
        return jsonify({"error": f"{our_symbol} is not a tradeable Delta Exchange symbol"}), 400

    try:
        product_id = client.get_product_id(delta_symbol)
        if leverage_int:
            client.set_leverage(product_id, leverage_int)
        result = client.place_order(
            product_id=product_id, side=side, size=size_int, order_type=order_type,
            limit_price=limit_price, stop_price=stop_price, reduce_only=reduce_only,
        )
        order_id = result.get("id") or result.get("order_id") if isinstance(result, dict) else None
        _audit_trade(
            user_id, "order_placed", order_id,
            details={"symbol": our_symbol, "side": side, "order_type": order_type,
                     "size": size_int, "reduce_only": reduce_only},
        )
        return jsonify({"order": result}), 201
    except DeltaTradingError as e:
        from app.services.error_tracking import capture
        capture(e, route="place_order", symbol=our_symbol, side=side, size=size_int)
        _audit_trade(
            user_id, "order_rejected", status="rejected",
            details={"symbol": our_symbol, "side": side, "order_type": order_type,
                     "size": size_int, "reduce_only": reduce_only},
        )
        return jsonify({"error": str(e)}), e.status_code or 400


@trading_bp.route("/orders/<int:order_id>", methods=["DELETE"])
@approved_required
def cancel_order(order_id):
    if order_id <= 0:
        return jsonify({"error": "order_id must be greater than zero"}), 400
    try:
        product_id = _positive_int(request.args.get("product_id"), "product_id")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    client, err = _client_or_error()
    if err:
        return err
    try:
        result = client.cancel_order(order_id, product_id)
        _audit_trade(
            get_jwt_identity(), "order_cancelled", order_id,
            details={"product_id": product_id},
        )
        return jsonify({"order": result}), 200
    except DeltaTradingError as e:
        _audit_trade(
            get_jwt_identity(), "order_cancel_rejected", order_id, status="rejected",
            details={"product_id": product_id},
        )
        return jsonify({"error": str(e)}), e.status_code or 400
