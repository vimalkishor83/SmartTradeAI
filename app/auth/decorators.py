from functools import wraps
from flask import jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from app.models.user import User


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            verify_jwt_in_request()
        except Exception:
            return jsonify({"error": "Authentication required"}), 401
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
