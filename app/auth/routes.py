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
@limiter.limit("3 per minute;15 per hour")
def register():
    data = request.get_json() or {}

    # Honeypot: a hidden form field real users never fill in. Bots that
    # blindly fill every input on the page get silently accepted-and-ignored
    # (no error, so the bot doesn't learn its submission was rejected) rather
    # than actually creating an account.
    if (data.get("website") or "").strip():
        return jsonify({
            "message": "Registration successful — your account is pending admin approval.",
        }), 201

    required = ["username", "email", "password"]
    if not all(k in data for k in required):
        return jsonify({"error": "Missing required fields"}), 400

    if not data.get("accept_terms"):
        return jsonify({"error": "You must accept the Terms of Service and Privacy Policy"}), 400

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
        # Self-registration always lands pending — an admin must approve
        # before the account gets full access (see require_approved decorator).
        approval_status="pending",
    )
    user.set_password(data["password"])
    db.session.add(user)
    db.session.commit()

    _audit(user.id, "register", "user", str(user.id))

    from app.services.tokens import make_verify_token
    from app.services.mailer import send_verification_email, send_admin_new_signup_alert
    send_verification_email(user, make_verify_token(user.id))

    admin_role = Role.query.filter_by(name="admin").first()
    if admin_role:
        admin_emails = [u.email for u in User.query.filter_by(role_id=admin_role.id).all()]
        send_admin_new_signup_alert(admin_emails, user)

    access_token = create_access_token(identity=str(user.id))
    refresh_token = create_refresh_token(identity=str(user.id))

    return jsonify({
        "message": "Registration successful — check your email to verify your address. "
                    "Your account is also pending admin approval before full access unlocks.",
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
        # Audited even though the account may not exist / user_id is None —
        # gives the admin a signal for credential-stuffing/brute-force
        # patterns (repeated failures against one email or from one IP),
        # which the audit log couldn't previously show at all.
        _audit(user.id if user else None, "login_failed", "user", data.get("email", ""), status="failed")
        return jsonify({"error": "Invalid credentials"}), 401

    if not user.is_active:
        _audit(user.id, "login_failed", "user", str(user.id), status="failed")
        return jsonify({"error": "Account is disabled"}), 403

    # ── 2FA check ──────────────────────────────────────────────────────────────
    if user.totp_enabled and user.totp_secret:
        totp_code = data.get("totp_code", "").strip()
        if not totp_code:
            # Signal to frontend: credentials OK but 2FA required
            return jsonify({
                "totp_required": True,
                "message": "2FA code required",
                "partial_token": create_access_token(
                    identity=str(user.id),
                    additional_claims={"totp_pending": True},
                    expires_delta=__import__("datetime").timedelta(minutes=5),
                ),
            }), 202

        import pyotp, json as _json
        totp = pyotp.TOTP(user.totp_secret)
        # Check TOTP code
        if not totp.verify(totp_code, valid_window=1):
            # Check backup codes
            backup_ok = False
            from app.extensions import bcrypt as _bcrypt
            backup_codes = _json.loads(user.totp_backup_codes or "[]")
            for i, hashed in enumerate(backup_codes):
                if _bcrypt.check_password_hash(hashed, totp_code):
                    backup_codes.pop(i)
                    user.totp_backup_codes = _json.dumps(backup_codes)
                    backup_ok = True
                    break
            if not backup_ok:
                return jsonify({"error": "Invalid 2FA code"}), 401

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


# ── Email verification ─────────────────────────────────────────────────────

@auth_bp.route("/verify-email", methods=["POST"])
@limiter.limit("10 per minute")
def verify_email():
    from app.services.tokens import read_verify_token
    token = (request.get_json() or {}).get("token", "")
    user_id = read_verify_token(token)
    if not user_id:
        return jsonify({"error": "Invalid or expired verification link"}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "Invalid or expired verification link"}), 400

    user.is_verified = True
    db.session.commit()
    _audit(user.id, "email_verified", "user", str(user.id))
    return jsonify({"message": "Email verified successfully"}), 200


@auth_bp.route("/resend-verification", methods=["POST"])
@login_required
@limiter.limit("3 per minute")
def resend_verification():
    user = get_current_user()
    if user.is_verified:
        return jsonify({"message": "Email already verified"}), 200

    from app.services.tokens import make_verify_token
    from app.services.mailer import send_verification_email
    send_verification_email(user, make_verify_token(user.id))
    return jsonify({"message": "Verification email sent"}), 200


# ── Password reset ─────────────────────────────────────────────────────────

@auth_bp.route("/forgot-password", methods=["POST"])
@limiter.limit("3 per minute;10 per hour")
def forgot_password():
    email = (request.get_json() or {}).get("email", "")
    user = User.query.filter_by(email=email).first()
    # Always return the same response whether or not the email exists —
    # otherwise this endpoint becomes a way to enumerate registered emails.
    if user:
        from app.services.tokens import make_reset_token
        from app.services.mailer import send_password_reset_email
        send_password_reset_email(user, make_reset_token(user.id))
        _audit(user.id, "password_reset_requested", "user", str(user.id))
    return jsonify({"message": "If that email is registered, a reset link has been sent."}), 200


@auth_bp.route("/reset-password", methods=["POST"])
@limiter.limit("5 per minute")
def reset_password():
    from app.services.tokens import read_reset_token
    data = request.get_json() or {}
    token = data.get("token", "")
    new_password = data.get("password", "")

    if len(new_password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    user_id = read_reset_token(token)
    if not user_id:
        return jsonify({"error": "Invalid or expired reset link"}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "Invalid or expired reset link"}), 400

    user.set_password(new_password)
    db.session.commit()
    _audit(user.id, "password_reset", "user", str(user.id))
    return jsonify({"message": "Password reset successfully — you can now log in."}), 200


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


def _audit(user_id, action, resource, resource_id, status="success"):
    try:
        log = AuditLog(
            user_id=user_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent", ""),
            status=status,
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        pass


# ── 2FA Management Endpoints ───────────────────────────────────────────────────

@auth_bp.route("/2fa/setup", methods=["POST"])
@login_required
def setup_2fa():
    """Generate a new TOTP secret and return QR code URI for the authenticator app."""
    import pyotp, io, base64
    user = get_current_user()

    secret = pyotp.random_base32()
    totp   = pyotp.TOTP(secret)
    uri    = totp.provisioning_uri(name=user.email, issuer_name="SmartTradeAI")

    try:
        import qrcode as _qr
        qr = _qr.make(uri)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        qr_b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        qr_b64 = None

    # Store secret temporarily (not yet enabled — confirmed on verify)
    user.totp_secret  = secret
    user.totp_enabled = False
    db.session.commit()

    return jsonify({
        "secret":      secret,
        "otpauth_uri": uri,
        "qr_code":     qr_b64,
        "message":     "Scan the QR code with Google Authenticator or Authy, then verify.",
    }), 200


@auth_bp.route("/2fa/verify", methods=["POST"])
@login_required
def verify_2fa():
    """Confirm the TOTP code entered by user — enables 2FA and returns backup codes."""
    import pyotp, json as _json, secrets as _sec
    from app.extensions import bcrypt as _bcrypt

    user = get_current_user()
    data = request.get_json() or {}
    code = data.get("code", "").strip()

    if not user.totp_secret:
        return jsonify({"error": "Run /2fa/setup first"}), 400

    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(code, valid_window=1):
        return jsonify({"error": "Invalid code — check your authenticator app time sync"}), 400

    # Generate 8 one-time backup codes
    raw_codes    = [_sec.token_hex(4).upper() for _ in range(8)]
    hashed_codes = [_bcrypt.generate_password_hash(c).decode() for c in raw_codes]

    user.totp_enabled      = True
    user.totp_backup_codes = _json.dumps(hashed_codes)
    db.session.commit()

    _audit(user.id, "2fa_enabled", "user", str(user.id))
    return jsonify({
        "message":      "2FA enabled successfully",
        "backup_codes": raw_codes,  # Show once — user must save these
    }), 200


@auth_bp.route("/2fa/disable", methods=["POST"])
@login_required
def disable_2fa():
    """Disable 2FA — requires current password confirmation."""
    import pyotp
    user = get_current_user()
    data = request.get_json() or {}

    if not user.check_password(data.get("password", "")):
        return jsonify({"error": "Password incorrect"}), 403

    # Optionally also accept TOTP code if user still has access
    if user.totp_enabled and user.totp_secret and data.get("totp_code"):
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(data["totp_code"], valid_window=1):
            return jsonify({"error": "Invalid 2FA code"}), 400

    user.totp_enabled      = False
    user.totp_secret       = None
    user.totp_backup_codes = None
    db.session.commit()

    _audit(user.id, "2fa_disabled", "user", str(user.id))
    return jsonify({"message": "2FA disabled"}), 200


@auth_bp.route("/push/vapid-key", methods=["GET"])
def push_vapid_key():
    """Return the VAPID public key so the browser can subscribe."""
    from flask import current_app
    key = current_app.config.get("VAPID_PUBLIC_KEY", "")
    return jsonify({"vapid_public_key": key}), 200


@auth_bp.route("/push/subscribe", methods=["POST"])
@login_required
def push_subscribe():
    """Save a browser PushSubscription for the current user."""
    import json as _json
    user = get_current_user()
    data = request.get_json() or {}
    subscription = data.get("subscription")
    if not subscription:
        return jsonify({"error": "subscription required"}), 400
    user.push_subscription = _json.dumps(subscription) if isinstance(subscription, dict) else subscription
    user.push_enabled = True
    db.session.commit()
    return jsonify({"message": "Push subscription saved"}), 200


@auth_bp.route("/push/unsubscribe", methods=["POST"])
@login_required
def push_unsubscribe():
    """Remove push subscription for the current user."""
    user = get_current_user()
    user.push_subscription = None
    user.push_enabled = False
    db.session.commit()
    return jsonify({"message": "Push subscription removed"}), 200


@auth_bp.route("/2fa/status", methods=["GET"])
@login_required
def status_2fa():
    """Return whether 2FA is enabled for current user."""
    user = get_current_user()
    return jsonify({
        "totp_enabled": user.totp_enabled,
        "has_backup_codes": bool(user.totp_backup_codes),
    }), 200
