from functools import wraps
from flask import jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from app.models.user import User


def login_required(f):
    """Requires a valid JWT *and* an account that is still active.

    The is_active check matters because deactivating a user only stops them
    issuing NEW tokens — any access token already in their hands stays
    cryptographically valid until it expires. Without this lookup (which every
    other decorator in this module already performs) a deactivated or banned
    account kept full access to the ~70 endpoints guarded by the bare
    @login_required for the remaining lifetime of its token.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            verify_jwt_in_request()
        except Exception:
            return jsonify({"error": "Authentication required"}), 401

        user_id = get_jwt_identity()
        user = User.query.get(int(user_id)) if user_id else None
        if not user or not user.is_active:
            return jsonify({"error": "User not found or inactive"}), 403

        return f(*args, **kwargs)
    return decorated


def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            try:
                verify_jwt_in_request()
            except Exception:
                return jsonify({"error": "Authentication required"}), 401

            user_id = get_jwt_identity()
            user = User.query.get(int(user_id))
            if not user or not user.is_active:
                return jsonify({"error": "User not found or inactive"}), 403

            if user.role.name not in roles:
                return jsonify({"error": "Insufficient permissions"}), 403

            return f(*args, **kwargs)
        return decorated
    return decorator


def admin_required(f):
    return roles_required("admin")(f)


def super_admin_required(f):
    """Gates admin endpoints that actually change something (create/edit/
    delete users, edit platform config, API configs, brokers, referral
    codes, clearing logs, etc.) behind User.is_super_admin, on top of the
    existing admin-role check. A regular "admin" role account can still
    view every admin page (they hit the @admin_required GET endpoints
    fine) but gets a 403 the moment they try to mutate anything — matches
    the split between "can see" and "can change" admins."""
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            verify_jwt_in_request()
        except Exception:
            return jsonify({"error": "Authentication required"}), 401

        user_id = get_jwt_identity()
        user = User.query.get(int(user_id))
        if not user or not user.is_active:
            return jsonify({"error": "User not found or inactive"}), 403

        if not user.role or user.role.name != "admin":
            return jsonify({"error": "Insufficient permissions"}), 403

        if not user.is_super_admin:
            return jsonify({"error": "This action requires super admin access"}), 403

        return f(*args, **kwargs)
    return decorated


def premium_required(f):
    return roles_required("admin", "premium", "pro")(f)


def approved_required(f):
    """Blocks endpoints that need full account access (signals, portfolio,
    trading, etc.) for users still in the self-registration "pending" queue
    or who were rejected. Admins bypass this — an admin account is always
    approval_status="approved" by construction, but this also lets an admin
    fix their own account if something goes sideways."""
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            verify_jwt_in_request()
        except Exception:
            return jsonify({"error": "Authentication required"}), 401

        user_id = get_jwt_identity()
        user = User.query.get(int(user_id))
        if not user or not user.is_active:
            return jsonify({"error": "User not found or inactive"}), 403

        if user.approval_status != "approved":
            return jsonify({
                "error": "Account pending approval",
                "approval_status": user.approval_status,
                "message": "Your account is awaiting admin approval before you can access this feature.",
            }), 403

        return f(*args, **kwargs)
    return decorated


def get_current_user():
    user_id = get_jwt_identity()
    return User.query.get(int(user_id)) if user_id else None


def page_admin_required(f):
    """Server-side admin gate for rendered HTML pages (app/views.py).

    Distinct from admin_required, which returns JSON 401/403 — correct for
    /api/v1/* but wrong for a browser navigation, where the user should be
    redirected to the login page instead of shown a JSON blob.

    Works because JWT_TOKEN_LOCATION includes "cookies" and /auth/login calls
    set_access_cookies, so a normal page request carries the token. Previously
    the admin pages had NO server-side check at all: access was enforced only
    by client-side JS reading data-requires-admin, so an unauthenticated GET
    still returned 200 with the full admin panel markup and its JS.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        from flask import redirect, url_for, request
        try:
            verify_jwt_in_request()
        except Exception:
            _notify_security_admin_unauthorized(None, "no valid session")
            return redirect(url_for("views.login"))

        user_id = get_jwt_identity()
        user = User.query.get(int(user_id)) if user_id else None
        if not user or not user.is_active:
            _notify_security_admin_unauthorized(None, "inactive or unknown account")
            return redirect(url_for("views.login"))
        if not user.role or user.role.name != "admin":
            _notify_security_admin_unauthorized(user, "not an admin account")
            return redirect(url_for("views.dashboard"))

        return f(*args, **kwargs)
    return decorated


def _notify_security_admin_unauthorized(user, reason: str):
    """Fires the moment someone loads an /admin/* HTML page without valid
    admin access — a genuinely security-relevant signal distinct from
    the audit log (which only records actions by known, authenticated
    users). Gated by PlatformConfig.telegram_security_notify_admin_
    unauthorized, editable from /admin/security."""
    try:
        from flask import request
        from datetime import datetime
        from app.services.platform_config import get_platform_config
        if not get_platform_config().get("telegram_security_notify_admin_unauthorized", True):
            return
        from app.tasks.notification_tasks import send_security_alert
        when = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
        who = f"`{user.username}` ({user.full_name})" if user else "_anonymous_"
        send_security_alert(
            f"⛔ *UNAUTHORIZED ADMIN ACCESS*\n\n"
            f"👤 User: {who}\n"
            f"📄 Page: `{request.path}`\n"
            f"🌐 IP: `{request.remote_addr}`\n"
            f"❓ Reason: {reason}\n"
            f"🕐 Time: `{when}`"
        )
    except Exception:
        pass


def min_tier_required(min_tier_level):
    """Gate an endpoint on the free->basic->premium->pro subscription ladder
    (Subscription.tier_level) rather than hardcoding plan names — e.g.
    @min_tier_required(2) admits premium(2), pro(3), and admin(99), and
    rejects free(0)/basic(1). Prefer this over roles_required()/premium_required()
    for anything gated purely by "which paid tier", since it stays correct
    automatically if more tiers are inserted later; use subscription_feature_required
    instead when the gate is a specific capability flag rather than a tier."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            try:
                verify_jwt_in_request()
            except Exception:
                return jsonify({"error": "Authentication required"}), 401

            user_id = get_jwt_identity()
            user = User.query.get(int(user_id))
            if not user or not user.is_active:
                return jsonify({"error": "User not found or inactive"}), 403

            sub = user.subscription
            tier = sub.tier_level if sub else 0
            if tier < min_tier_level:
                return jsonify({
                    "error": "This feature requires a higher plan.",
                    "current_plan": sub.name if sub else "free",
                    "required_tier_level": min_tier_level,
                }), 403

            return f(*args, **kwargs)
        return decorated
    return decorator


def subscription_feature_required(flag_name):
    """Gate an endpoint on a Subscription-level feature flag (backtesting_enabled,
    ai_enabled, ...) rather than the coarser role-based premium_required — lets the
    Subscription tiers actually control feature access instead of only Role."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            try:
                verify_jwt_in_request()
            except Exception:
                return jsonify({"error": "Authentication required"}), 401

            user_id = get_jwt_identity()
            user = User.query.get(int(user_id))
            if not user or not user.is_active:
                return jsonify({"error": "User not found or inactive"}), 403

            sub = user.subscription
            if not sub or not getattr(sub, flag_name, False):
                return jsonify({
                    "error": f"This feature requires a plan with '{flag_name}' enabled. "
                             f"Your current plan: {sub.name if sub else 'none'}.",
                }), 403

            return f(*args, **kwargs)
        return decorated
    return decorator
