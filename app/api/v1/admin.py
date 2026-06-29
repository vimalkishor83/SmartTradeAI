import psutil
from flask import Blueprint, request, jsonify
from app.extensions import db
from app.models.user import User, Role, Subscription
from app.models.asset import Asset
from app.models.api_config import APIConfig
from app.models.audit import AuditLog, SystemLog
from app.models.signal import Signal, SignalHistory
from app.auth.decorators import admin_required
from datetime import datetime, timedelta

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/dashboard", methods=["GET"])
@admin_required
def dashboard():
    total_users = User.query.count()
    active_users = User.query.filter_by(is_active=True).count()
    total_signals = Signal.query.count()
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    signals_today = Signal.query.filter(Signal.generated_at >= today).count()

    history = SignalHistory.query
    total_h = history.count()
    wins = history.filter(SignalHistory.outcome == "win").count()
    win_rate = round(wins / total_h * 100, 1) if total_h else 0

    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    return jsonify({
        "users": {"total": total_users, "active": active_users},
        "signals": {"total": total_signals, "today": signals_today, "win_rate": win_rate},
        "system": {
            "cpu_pct": cpu,
            "memory_pct": mem.percent,
            "memory_used_gb": round(mem.used / 1e9, 2),
            "disk_pct": disk.percent,
        },
        "db_status": "healthy",
    }), 200


@admin_bp.route("/users", methods=["GET"])
@admin_required
def list_users():
    page = int(request.args.get("page", 1))
    search = request.args.get("search", "")
    query = User.query
    if search:
        query = query.filter(
            User.username.ilike(f"%{search}%") | User.email.ilike(f"%{search}%")
        )
    users = query.order_by(User.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return jsonify({
        "users": [u.to_dict() for u in users.items],
        "total": users.total,
        "pages": users.pages,
    }), 200


@admin_bp.route("/users/<int:user_id>", methods=["PUT"])
@admin_required
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    allowed = ["is_active", "role_id", "subscription_id", "is_verified"]
    for f in allowed:
        if f in data:
            setattr(user, f, data[f])
    db.session.commit()
    return jsonify(user.to_dict()), 200


@admin_bp.route("/users/<int:user_id>", methods=["DELETE"])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return jsonify({"message": "User deleted"}), 200


@admin_bp.route("/api-configs", methods=["GET"])
@admin_required
def list_api_configs():
    configs = APIConfig.query.all()
    return jsonify({"configs": [c.to_dict() for c in configs]}), 200


@admin_bp.route("/api-configs", methods=["POST"])
@admin_required
def create_api_config():
    data = request.get_json()
    config = APIConfig(**{k: data[k] for k in data if hasattr(APIConfig, k)})
    db.session.add(config)
    db.session.commit()
    return jsonify(config.to_dict()), 201


@admin_bp.route("/api-configs/<int:cfg_id>", methods=["PUT"])
@admin_required
def update_api_config(cfg_id):
    config = APIConfig.query.get_or_404(cfg_id)
    data = request.get_json()
    for k, v in data.items():
        if hasattr(config, k):
            setattr(config, k, v)
    db.session.commit()
    return jsonify(config.to_dict()), 200


@admin_bp.route("/audit-logs", methods=["GET"])
@admin_required
def audit_logs():
    page = int(request.args.get("page", 1))
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()) \
        .paginate(page=page, per_page=50, error_out=False)
    return jsonify({
        "logs": [l.to_dict() for l in logs.items],
        "total": logs.total,
        "pages": logs.pages,
    }), 200


@admin_bp.route("/system-logs", methods=["GET"])
@admin_required
def system_logs():
    page = int(request.args.get("page", 1))
    level = request.args.get("level")
    query = SystemLog.query
    if level:
        query = query.filter_by(level=level.upper())
    logs = query.order_by(SystemLog.created_at.desc()) \
        .paginate(page=page, per_page=50, error_out=False)
    return jsonify({
        "logs": [l.to_dict() for l in logs.items],
        "total": logs.total,
    }), 200
