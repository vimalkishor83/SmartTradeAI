from datetime import datetime
from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, set_access_cookies,
    set_refresh_cookies, unset_jwt_cookies
)
from app.extensions import db, limiter
from app.models.user import User, Role, Subscription
from app.models.audit import AuditLog
from app.auth.decorators import login_required, get_current_user

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["POST"])
@limiter.limit("5 per minute")
def register():
    data = request.get_json()
    required = ["username", "email", "password"]
    if not all(k in data for k in required):
        return jsonify({"error": "Missing required fields"}), 400

    if User.query.filter_by(username=data["username"]).first():
        return jsonify({"error": "Username already taken"}), 409
    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"error": "Email already registered"}), 409

    free_role = Role.query.filter_by(name="free").first()
    free_sub = Subscription.query.filter_by(name="free").first()

    user = User(
        username=data["username"],
        email=data["email"],
        first_name=data.get("first_name", ""),
        last_name=data.get("last_name", ""),
        role_id=free_role.id,
        subscription_id=free_sub.id if free_sub else None,
    )
    user.set_password(data["password"])
    db.session.add(user)
    db.session.commit()

    _audit(user.id, "register", "user", str(user.id))

    access_token = create_access_token(identity=str(user.id))
    refresh_token = create_refresh_token(identity=str(user.id))

    return jsonify({
        "message": "Registration successful",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": user.to_dict(),
    }), 201


@auth_bp.route("/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    data = request.get_json()
    if not data or not data.get("email") or not data.get("password"):
        return jsonify({"error": "Email and password required"}), 400

    user = User.query.filter_by(email=data["email"]).first()
    if not user or not user.check_password(data["password"]):
        return jsonify({"error": "Invalid credentials"}), 401

    if not user.is_active:
        return jsonify({"error": "Account is disabled"}), 403

    user.last_login = datetime.utcnow()
    db.session.commit()

    access_token = create_access_token(identity=str(user.id))
    refresh_token = create_refresh_token(identity=str(user.id))

    _audit(user.id, "login", "user", str(user.id))

    response = jsonify({
        "message": "Login successful",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": user.to_dict(),
    })
    set_access_cookies(response, access_token)
    set_refresh_cookies(response, refresh_token)
    return response, 200


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    user = get_current_user()
    if user:
        _audit(user.id, "logout", "user", str(user.id))
    response = jsonify({"message": "Logged out successfully"})
    unset_jwt_cookies(response)
    return response, 200


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    user_id = get_jwt_identity()
    access_token = create_access_token(identity=user_id)
    return jsonify({"access_token": access_token}), 200


@auth_bp.route("/me", methods=["GET"])
@login_required
def me():
    user = get_current_user()
    return jsonify(user.to_dict()), 200


@auth_bp.route("/me", methods=["PUT"])
@login_required
def update_profile():
    user = get_current_user()
    data = request.get_json()
    allowed = ["first_name", "last_name", "phone", "theme", "email_notifications",
               "telegram_chat_id", "telegram_enabled", "push_enabled",
               "account_size", "risk_per_trade_pct", "min_confidence_filter"]
    for field in allowed:
        if field in data:
            setattr(user, field, data[field])

    if "password" in data and "current_password" in data:
        if not user.check_password(data["current_password"]):
            return jsonify({"error": "Current password is incorrect"}), 400
        user.set_password(data["password"])

    db.session.commit()
    return jsonify({"message": "Profile updated", "user": user.to_dict()}), 200


@auth_bp.route("/me/asset-preferences", methods=["GET"])
@login_required
def get_asset_preferences():
    from app.models.user import UserAssetPreference
    from app.models.asset import Asset
    user  = get_current_user()
    prefs = {p.asset_id: p.enabled for p in UserAssetPreference.query.filter_by(user_id=user.id).all()}
    assets = Asset.query.filter_by(is_active=True).order_by(Asset.market, Asset.symbol).all()
    return jsonify({
        "assets": [
            {"id": a.id, "symbol": a.symbol, "name": a.name, "market": a.market,
             "enabled": prefs.get(a.id, True)}  # default: all enabled
            for a in assets
        ]
    }), 200


@auth_bp.route("/me/asset-preferences", methods=["PUT"])
@login_required
def save_asset_preferences():
    from app.models.user import UserAssetPreference
    user  = get_current_user()
    data  = request.get_json()
    # data = {"preferences": {"asset_id": true/false, ...}}
    prefs_in = data.get("preferences", {})
    existing = {p.asset_id: p for p in UserAssetPreference.query.filter_by(user_id=user.id).all()}

    for asset_id_str, enabled in prefs_in.items():
        asset_id = int(asset_id_str)
        if asset_id in existing:
            existing[asset_id].enabled = bool(enabled)
        else:
            db.session.add(UserAssetPreference(user_id=user.id, asset_id=asset_id, enabled=bool(enabled)))

    db.session.commit()
    # Invalidate TA/MTF cache for this user (clear all market variants)
    from app.extensions import cache
    for mkt in ["all", "crypto", "forex", "commodity", "indian_stock", "index"]:
        cache.delete(f"ta_summary_{user.id}_{mkt}")
        cache.delete(f"mtf_matrix_{user.id}_{mkt}")
    return jsonify({"message": "Preferences saved"}), 200


def _audit(user_id, action, resource, resource_id):
    try:
        log = AuditLog(
            user_id=user_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent", ""),
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        pass
