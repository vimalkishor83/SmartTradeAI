from datetime import datetime
from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, set_access_cookies,
    set_refresh_cookies, unset_jwt_cookies
)
from app.extensions import db, limiter
from app.models.user import User, Role, Subscription, ReferralCode, Broker
from app.models.audit import AuditLog
from app.auth.decorators import login_required, get_current_user

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/brokers", methods=["GET"])
def list_active_brokers():
    """Public (no auth) broker list for the registration form's dropdown —
    unauthenticated visitors can't hit the admin-only /api/v1/admin/brokers.
    Admin manages the underlying list from the Admin Panel."""
    brokers = Broker.query.filter_by(is_active=True).order_by(Broker.sort_order, Broker.name).all()
    return jsonify({"brokers": [b.to_dict() for b in brokers]}), 200


@auth_bp.route("/referral-codes/<code>/check", methods=["GET"])
@limiter.limit("30 per minute")
def check_referral_code(code):
    """Public live-validation for the registration form — lets the UI show
    a checkmark/error as the user types, without waiting for full signup.
    Only exposes valid/invalid + which plan it unlocks, nothing else."""
    rc = ReferralCode.query.filter_by(code=(code or "").strip().upper()).first()
    if not rc or not rc.is_valid():
        return jsonify({"valid": False}), 200
    return jsonify({
        "valid": True,
        "unlocks_plan": rc.referred_subscription.name if rc.referred_subscription else None,
        "broker_name": rc.broker_name,
    }), 200


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

    broker_id_raw = data.get("broker_id")
    broker = None
    if broker_id_raw:
        broker = Broker.query.filter_by(id=broker_id_raw, is_active=True).first()
        if not broker:
            return jsonify({"error": "Selected broker is invalid"}), 400
        if not (data.get("broker_account_id") or "").strip():
            return jsonify({"error": "Broker Account ID is required once a broker is selected"}), 400

    free_role = Role.query.filter_by(name="free").first()
    free_sub = Subscription.query.filter_by(name="free").first()

    # A valid, active referral/partner-broker code grants that code's role
    # and subscription (typically premium) instead of the default free tier.
    # Invalid/inactive/expired/exhausted codes are silently ignored — the
    # signup still succeeds, it just falls back to the free tier, so a typo
    # doesn't block registration.
    referral_code_raw = (data.get("referral_code") or "").strip()
    referral = None
    if referral_code_raw:
        referral = ReferralCode.query.filter_by(code=referral_code_raw).first()
        if not referral or not referral.is_valid():
            referral = None

    role_id = referral.referred_role_id if (referral and referral.referred_role_id) else free_role.id
    subscription_id = (
        referral.referred_subscription_id
        if (referral and referral.referred_subscription_id)
        else (free_sub.id if free_sub else None)
    )

    user = User(
        username=data["username"],
        email=data["email"],
        first_name=data.get("first_name", ""),
        last_name=data.get("last_name", ""),
        broker_id=broker.id if broker else None,
        broker_account_id=(data.get("broker_account_id") or "").strip() or None,
        referral_code_id=referral.id if referral else None,
        role_id=role_id,
        subscription_id=subscription_id,
        # Self-registration always lands pending — an admin must approve
        # before the account gets full access (see require_approved decorator).
        # A valid referral still requires approval; it only changes which
        # tier the account lands in once approved.
        approval_status="pending",
    )
    user.set_password(data["password"])
    db.session.add(user)

    if referral:
        referral.uses_count = (referral.uses_count or 0) + 1

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
        "referral_applied": bool(referral),
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
    # Re-check the account on every refresh. /login already refuses a
    # deactivated user, but refresh tokens live for 30 days — without this
    # lookup a user deactivated mid-window could keep minting fresh 24h access
    # tokens for the rest of that window, so deactivation wouldn't actually
    # revoke anything until the refresh token itself expired.
    user = User.query.get(int(user_id)) if user_id else None
    if not user or not user.is_active:
        return jsonify({"error": "Account is disabled"}), 403

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


@auth_bp.route("/me/export", methods=["GET"])
@login_required
def export_my_data():
    """Full personal-data export (GDPR/CCPA-style right to portability) —
    every table that stores this user's data, as one JSON document."""
    from app.models.watchlist import Watchlist
    from app.models.portfolio import Portfolio
    from app.models.backtest import Backtest
    from app.models.journal import JournalEntry
    from app.models.notification import Notification
    from app.models.audit import AuditLog
    from app.models.api_config import UserBrokerCredential

    user = get_current_user()

    watchlists = []
    for wl in Watchlist.query.filter_by(user_id=user.id).all():
        watchlists.append({
            "name": wl.name,
            "items": [{"symbol": i.asset.symbol if i.asset else None,
                       "alert_price": i.alert_price} for i in wl.items.all()],
        })

    broker = UserBrokerCredential.query.filter_by(user_id=user.id).first()

    export = {
        "account": user.to_dict(),
        "watchlists": watchlists,
        "portfolio": [p.to_dict() for p in Portfolio.query.filter_by(user_id=user.id).all()],
        "backtests": [b.to_dict() for b in Backtest.query.filter_by(user_id=user.id).all()],
        "journal_entries": [j.to_dict() for j in JournalEntry.query.filter_by(user_id=user.id).all()],
        "notifications": [n.to_dict() for n in Notification.query.filter_by(user_id=user.id).all()],
        "audit_log": [{
            "action": a.action, "resource": a.resource, "status": a.status,
            "ip_address": a.ip_address, "created_at": a.created_at.isoformat() if a.created_at else None,
        } for a in AuditLog.query.filter_by(user_id=user.id).all()],
        # Broker connection status only — never the encrypted key/secret itself.
        "broker_connection": {"provider": broker.provider, "is_active": broker.is_active} if broker else None,
    }

    _audit(user.id, "data_exported", "user", str(user.id))
    return jsonify(export), 200


@auth_bp.route("/me", methods=["DELETE"])
@login_required
def delete_my_account():
    """Self-service account deletion. Requires current password confirmation
    (prevents a hijacked session / CSRF-adjacent mistake from nuking an
    account silently). Cascade-related tables (Watchlist, Portfolio,
    Notification, Backtest) are removed via the User model's
    cascade='all, delete-orphan' relationships; tables without a declared
    relationship (JournalEntry, UserAssetPreference, UserBrokerCredential,
    AuditLog) are deleted explicitly here first so the final user delete
    doesn't fail on a lingering foreign key."""
    from app.models.journal import JournalEntry
    from app.models.user import UserAssetPreference
    from app.models.api_config import UserBrokerCredential
    from app.models.audit import AuditLog

    user = get_current_user()
    data = request.get_json() or {}
    if not user.check_password(data.get("password", "")):
        return jsonify({"error": "Password incorrect"}), 403

    user_id = user.id
    JournalEntry.query.filter_by(user_id=user_id).delete()
    UserAssetPreference.query.filter_by(user_id=user_id).delete()
    UserBrokerCredential.query.filter_by(user_id=user_id).delete()
    # Audit rows keep user_id nullable specifically so a deletion audit trail
    # can survive the account itself being removed — null the FK, don't delete.
    AuditLog.query.filter_by(user_id=user_id).update({"user_id": None})

    _audit(None, "account_deleted", "user", str(user_id))
    db.session.delete(user)
    db.session.commit()

    response = jsonify({"message": "Account deleted"})
    unset_jwt_cookies(response)
    return response, 200


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

    # Never round-tripped back to the client (to_dict only exposes
    # has_telegram_bot_token), so the field arrives blank on every page
    # load by design — only touch the stored token when the user actually
    # typed a new one, never wipe it just because the field was empty.
    if data.get("telegram_bot_token"):
        user.set_telegram_bot_token(data["telegram_bot_token"])

    if "password" in data and "current_password" in data:
        if not user.check_password(data["current_password"]):
            return jsonify({"error": "Current password is incorrect"}), 400
        user.set_password(data["password"])

    db.session.commit()
    return jsonify({"message": "Profile updated", "user": user.to_dict()}), 200


def _resolve_telegram_token(user, override: str | None = None) -> str | None:
    """Per-user bot token first, then the request's just-typed-but-not-yet-
    saved override, then the platform-wide fallback bot (if an admin has
    configured one) — a user isn't required to run their own bot, but can."""
    from flask import current_app
    if override:
        return override
    own = user.get_telegram_bot_token()
    if own:
        return own
    return current_app.config.get("TELEGRAM_BOT_TOKEN")


@auth_bp.route("/me/telegram-find-chat-id", methods=["POST"])
@login_required
def find_telegram_chat_id():
    """
    Finding your own numeric Chat ID is the one genuinely fiddly step in
    setting up Telegram alerts. Telegram's getUpdates returns every message
    your bot has received — if you've just messaged it (per the Settings
    page guide), the chat ID is sitting right there, so auto-fill it
    instead of asking the user to read it out of a raw JSON blob by hand.
    """
    import requests
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    token = _resolve_telegram_token(user, data.get("bot_token"))
    if not token:
        return jsonify({"error": "Add your bot token first (or save it), then try again."}), 400

    try:
        resp = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=8)
    except requests.RequestException as e:
        return jsonify({"error": f"Could not reach Telegram: {e}"}), 502

    body = resp.json() if resp.content else {}
    if not body.get("ok"):
        return jsonify({"error": body.get("description", "Telegram rejected that bot token.")}), 400

    updates = body.get("result", [])
    if not updates:
        return jsonify({"error": "No messages found yet — open your bot in Telegram and send it any message, then try again."}), 404

    # Most recent sender wins — this account's own chat with the bot.
    chat = updates[-1].get("message", {}).get("chat", {})
    chat_id = chat.get("id")
    if not chat_id:
        return jsonify({"error": "Couldn't find a chat ID in your bot's recent messages."}), 404

    label = chat.get("username") or chat.get("first_name") or "you"
    return jsonify({"chat_id": str(chat_id), "message": f"Found it — chat with {label}."}), 200


@auth_bp.route("/me/telegram-test", methods=["POST"])
@login_required
def send_telegram_test():
    """
    Send one real Telegram message right now and report whether it actually
    worked. The scheduled sender (_send_telegram in notification_tasks.py)
    is fire-and-forget by design — fine for a background alert job, but it
    silently swallows every failure, so a user who mistyped their chat ID
    or never configured a bot has no way to find out except waiting for a
    real alert to silently never arrive. This exists purely to close that
    loop from the Settings page.
    """
    import requests
    user = get_current_user()
    data = request.get_json(silent=True) or {}

    token = _resolve_telegram_token(user, data.get("bot_token"))
    if not token:
        return jsonify({"error": "Add your own bot token in Settings first (see the guide above), or ask your admin to configure a shared one."}), 503

    chat_id = data.get("chat_id") or user.telegram_chat_id
    if not chat_id:
        return jsonify({"error": "Enter a Telegram Chat ID first, then save and try again."}), 400

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": f"✅ *SmartTrade AI* test notification\n\nIf you can read this, Telegram alerts are working for your account.",
                "parse_mode": "Markdown",
            },
            timeout=8,
        )
    except requests.RequestException as e:
        return jsonify({"error": f"Could not reach Telegram: {e}"}), 502

    body = resp.json() if resp.content else {}
    if resp.status_code == 200 and body.get("ok"):
        return jsonify({"message": "Test message sent — check Telegram."}), 200

    # Telegram's own error text (e.g. "chat not found", "bot was blocked by
    # the user") is far more actionable than a generic failure would be.
    reason = body.get("description", f"HTTP {resp.status_code}")
    return jsonify({"error": f"Telegram rejected the message: {reason}"}), 400


@auth_bp.route("/subscriptions", methods=["GET"])
@login_required
def list_subscriptions():
    """Plan comparison list — lets the frontend show what each tier
    unlocks (backtesting_enabled/ai_enabled/max_watchlist/max_alerts) so a
    free user can see exactly what upgrading buys them."""
    subs = Subscription.query.order_by(Subscription.price.asc()).all()
    return jsonify({"subscriptions": [{
        "id": s.id, "name": s.name, "price": s.price, "tier_level": s.tier_level,
        "signal_delay_minutes": s.signal_delay_minutes,
        "max_watchlist": s.max_watchlist, "max_alerts": s.max_alerts,
        "backtesting_enabled": s.backtesting_enabled, "ai_enabled": s.ai_enabled,
        "advanced_charts_enabled": s.advanced_charts_enabled,
        "broker_connect_enabled": s.broker_connect_enabled,
        "features": s.features or [],
    } for s in subs]}), 200


@auth_bp.route("/upgrade-request", methods=["POST"])
@login_required
@limiter.limit("5 per hour")
def request_upgrade():
    """No payment gateway is wired up yet (subscription_id is currently
    admin-assigned only, via PUT /api/v1/admin/users/<id>) — this is the
    self-service half of that: a free-tier user can signal upgrade intent
    without needing direct admin/DB access, and every admin gets notified
    to action it manually. Logged to AuditLog for a visible request trail."""
    user = get_current_user()
    data = request.get_json() or {}
    requested_plan = (data.get("plan") or "premium").strip()

    target = Subscription.query.filter_by(name=requested_plan).first()
    if not target:
        return jsonify({"error": f"Unknown plan '{requested_plan}'"}), 400
    if user.subscription_id == target.id:
        return jsonify({"error": f"You're already on the '{requested_plan}' plan"}), 400

    log = AuditLog(
        user_id=user.id, action="upgrade_request", resource="subscription",
        resource_id=requested_plan,
        ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent", ""),
    )
    db.session.add(log)

    # Notify every admin so the request doesn't require the user to email
    # anyone directly — mirrors the existing Notification-row delivery
    # pattern used throughout the app (signal alerts, watchlist alerts).
    from app.models.notification import Notification
    admin_role = Role.query.filter_by(name="admin").first()
    admins = User.query.filter_by(role_id=admin_role.id).all() if admin_role else []
    for admin in admins:
        db.session.add(Notification(
            user_id=admin.id,
            title=f"Upgrade request: {user.username}",
            message=f"{user.username} ({user.email}) requested the '{requested_plan}' plan "
                    f"(currently: {user.subscription.name if user.subscription else 'none'}).",
            notification_type="upgrade_request", channel="web",
        ))

    db.session.commit()
    return jsonify({"message": f"Upgrade request to '{requested_plan}' sent — an admin will review it shortly."}), 201


@auth_bp.route("/upgrade-request/pending", methods=["GET"])
@login_required
def get_pending_upgrade_requests():
    """Which plans the current user has an outstanding upgrade request for —
    used to keep the Settings page's Request buttons disabled across a page
    refresh instead of forgetting the request was ever made. There's no
    separate status field an admin marks resolved (admins action these by
    directly changing the user's subscription via PUT /admin/users/<id>),
    so "the requested plan doesn't match my current plan" is the signal:
    once an admin moves the user onto the plan they asked for, it's no
    longer pending by definition. (Edge case: if an admin approves a
    *different* plan than requested, or explicitly declines, the old
    request row has no way to reflect that and would still show as
    pending — acceptable for now; there's no reject/approve action in the
    admin UI for these requests to hook into.)"""
    user = get_current_user()
    current_plan = user.subscription.name if user.subscription else None

    logs = (AuditLog.query
            .filter_by(user_id=user.id, action="upgrade_request")
            .order_by(AuditLog.created_at.desc())
            .all())

    pending = set()
    seen_plans = set()
    for log in logs:
        plan = log.resource_id
        if plan in seen_plans:
            continue  # only the most recent request per plan matters
        seen_plans.add(plan)
        if plan != current_plan:
            pending.add(plan)

    return jsonify({"pending_plans": list(pending)}), 200


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
