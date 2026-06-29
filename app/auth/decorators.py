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
    return roles_required("admin", "premium")(f)


def get_current_user():
    user_id = get_jwt_identity()
    return User.query.get(int(user_id)) if user_id else None
