import time
import psutil
import requests
from flask import Blueprint, request, jsonify
from app.extensions import db
from app.models.user import User, Role, Subscription, Broker, ReferralCode
from app.models.asset import Asset
from app.models.api_config import APIConfig, APILog
from app.models.audit import AuditLog, SystemLog
from app.models.signal import Signal, SignalHistory
from app.auth.decorators import admin_required, super_admin_required
from datetime import datetime, timedelta

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/dashboard", methods=["GET"])
@admin_required
def dashboard():
    total_users  = User.query.count()
    active_users = User.query.filter_by(is_active=True).count()
    total_signals = Signal.query.count()
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    signals_today = Signal.query.filter(Signal.generated_at >= today).count()

    history = SignalHistory.query
    total_h = history.count()
    wins    = history.filter(SignalHistory.outcome == "win").count()
    win_rate = round(wins / total_h * 100, 1) if total_h else 0

    pending_users = User.query.filter_by(approval_status="pending").count()

    cpu  = psutil.cpu_percent(interval=0.1)
    mem  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    # API config summary
    total_apis  = APIConfig.query.count()
    active_apis = APIConfig.query.filter_by(status="active").count()
    paused_apis = APIConfig.query.filter_by(status="paused").count()
    error_apis  = APIConfig.query.filter_by(status="error").count()
    last_sync   = db.session.query(db.func.max(APIConfig.last_sync)).scalar()

    return jsonify({
        "users":   {"total": total_users, "active": active_users, "pending": pending_users},
        "signals": {"total": total_signals, "today": signals_today, "win_rate": win_rate},
        "system":  {
            "cpu_pct":       cpu,
            "memory_pct":    mem.percent,
            "memory_used_gb":round(mem.used / 1e9, 2),
            "disk_pct":      disk.percent,
        },
        "db_status": "healthy",
        "api_summary": {
            "total":    total_apis,
            "active":   active_apis,
            "paused":   paused_apis,
            "error":    error_apis,
            "last_sync":last_sync.isoformat() if last_sync else None,
        },
    }), 200


# ─── Platform Configuration ──────────────────────────────────────────────────

@admin_bp.route("/platform-config", methods=["GET"])
@admin_required
def get_platform_config_route():
    from app.services.platform_config import get_platform_config
    return jsonify(get_platform_config()), 200


@admin_bp.route("/platform-config", methods=["PUT"])
@super_admin_required
def update_platform_config_route():
    import re
    from app.models.platform_config import PlatformConfig
    from app.services.platform_config import invalidate_platform_config

    data = request.get_json() or {}
    row = PlatformConfig.get_singleton()

    if "disabled_nav_items" in data:
        if not isinstance(data["disabled_nav_items"], list):
            return jsonify({"error": "disabled_nav_items must be a list"}), 400
        row.disabled_nav_items = data["disabled_nav_items"]

    if "timeframes" in data:
        tfs = data["timeframes"]
        if not isinstance(tfs, list) or not tfs:
            return jsonify({"error": "timeframes must be a non-empty list"}), 400
        if not all(isinstance(tf, str) and re.match(r"^\d+[mhdw]$", tf) for tf in tfs):
            return jsonify({"error": "invalid timeframe token"}), 400
        row.timeframes = tfs

    db.session.commit()
    invalidate_platform_config()
    return jsonify(row.to_dict()), 200


# ─── Users ──────────────────────────────────────────────────────────────────

@admin_bp.route("/users", methods=["GET"])
@admin_required
def list_users():
    page   = int(request.args.get("page", 1))
    search = request.args.get("search", "")
    status = request.args.get("approval_status", "")
    query  = User.query
    if search:
        query = query.filter(
            User.username.ilike(f"%{search}%") | User.email.ilike(f"%{search}%")
        )
    if status:
        query = query.filter(User.approval_status == status)
    users = query.order_by(User.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return jsonify({"users": [u.to_dict() for u in users.items], "total": users.total, "pages": users.pages}), 200


@admin_bp.route("/users/pending", methods=["GET"])
@admin_required
def list_pending_users():
    """Self-registered accounts awaiting approval — surfaced separately from
    the main user list so the admin panel can show a pending badge/queue."""
    # No pagination here on purpose — an admin needs to see the FULL pending
    # queue to process approvals, and hiding some behind a page-2 would be
    # worse UX than a slightly larger response. The .limit() is only a
    # safety cap against a pathological case (e.g. a signup-spam burst),
    # not a normal-operation constraint.
    users = (User.query.filter_by(approval_status="pending")
             .order_by(User.created_at.asc()).limit(1000).all())
    return jsonify({"users": [u.to_dict() for u in users], "total": len(users)}), 200


@admin_bp.route("/users/<int:user_id>/approve", methods=["POST"])
@super_admin_required
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    user.approval_status = "approved"
    db.session.commit()
    return jsonify(user.to_dict()), 200


@admin_bp.route("/users/<int:user_id>/reject", methods=["POST"])
@super_admin_required
def reject_user(user_id):
    user = User.query.get_or_404(user_id)
    user.approval_status = "rejected"
    db.session.commit()
    return jsonify(user.to_dict()), 200


@admin_bp.route("/users/<int:user_id>", methods=["PUT"])
@super_admin_required
def update_user(user_id):
    """Also handles editing a user's own login identity (username/email)
    and resetting their password — needed so a super admin can fix up test
    accounts (or their own account) without going through the self-service
    /auth/me flow, which requires knowing the current password."""
    user = User.query.get_or_404(user_id)
    data = request.get_json()

    if "username" in data:
        new_username = (data["username"] or "").strip()
        if not new_username:
            return jsonify({"error": "Username cannot be empty"}), 400
        if User.query.filter(User.username == new_username, User.id != user.id).first():
            return jsonify({"error": "Username already taken"}), 409
        user.username = new_username

    if "email" in data:
        new_email = (data["email"] or "").strip()
        if not new_email:
            return jsonify({"error": "Email cannot be empty"}), 400
        if User.query.filter(User.email == new_email, User.id != user.id).first():
            return jsonify({"error": "Email already registered"}), 409
        user.email = new_email

    if data.get("password"):
        user.set_password(data["password"])

    for f in ["is_active", "role_id", "subscription_id", "is_verified",
              "approval_status", "is_super_admin", "first_name", "last_name"]:
        if f in data:
            setattr(user, f, data[f])

    db.session.commit()
    _audit_admin_action(user.id, "admin_update_user")
    return jsonify(user.to_dict()), 200


@admin_bp.route("/roles", methods=["GET"])
@admin_required
def list_roles():
    """Populates the role dropdown for admin-side user creation/editing.
    Small, fixed set (admin/pro/premium/basic/free per the seed data) — not
    worth hardcoding in the frontend since role names/ids aren't guaranteed
    identical across every deployment's seed.

    Ordered least-to-most-privileged (not by id) specifically so a <select>
    built from this list defaults to its first/lowest-privilege option —
    "admin" happens to be seed row 1, so id-order made a forgotten role
    selection on Create Test User default to handing out admin access,
    exactly backwards from what a safe default should do. Unrecognized role
    names (a custom deployment's seed) sort after the known ones rather
    than disappearing.
    """
    priority = {"free": 0, "basic": 1, "premium": 2, "pro": 3, "admin": 4}
    roles = Role.query.all()
    roles.sort(key=lambda r: (priority.get(r.name, len(priority)), r.name))
    return jsonify({"roles": [{"id": r.id, "name": r.name, "description": r.description} for r in roles]}), 200


@admin_bp.route("/users", methods=["POST"])
@super_admin_required
def create_user():
    """
    Admin-created accounts — for handing working credentials to testers/
    stakeholders without them going through self-registration (which lands
    pending until an admin approves it anyway). Skips that queue entirely:
    approved, verified, and usable immediately, since an admin is directly
    vouching for the account rather than a stranger self-registering.
    """
    data = request.get_json() or {}
    if not all((data.get(f) or "").strip() if isinstance(data.get(f), str) else data.get(f) for f in ["username", "email", "password"]):
        return jsonify({"error": "username, email, and password are required"}), 400

    if User.query.filter_by(username=data["username"]).first():
        return jsonify({"error": "Username already taken"}), 409
    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"error": "Email already registered"}), 409

    role_id = data.get("role_id")
    if role_id and not Role.query.get(role_id):
        return jsonify({"error": "Invalid role"}), 400
    if not role_id:
        free_role = Role.query.filter_by(name="free").first()
        role_id = free_role.id if free_role else None

    subscription_id = data.get("subscription_id")
    if subscription_id and not Subscription.query.get(subscription_id):
        return jsonify({"error": "Invalid subscription"}), 400
    if not subscription_id:
        free_sub = Subscription.query.filter_by(name="free").first()
        subscription_id = free_sub.id if free_sub else None

    user = User(
        username=data["username"],
        email=data["email"],
        first_name=(data.get("first_name") or "").strip(),
        last_name=(data.get("last_name") or "").strip(),
        role_id=role_id,
        subscription_id=subscription_id,
        is_active=True,
        is_verified=True,
        approval_status="approved",
    )
    user.set_password(data["password"])
    db.session.add(user)
    db.session.commit()

    _audit_admin_action(user.id, "admin_create_user")

    return jsonify(user.to_dict()), 201


def _audit_admin_action(target_user_id, action):
    try:
        from flask_jwt_extended import get_jwt_identity
        db.session.add(AuditLog(
            user_id=int(get_jwt_identity()), action=action,
            resource="user", resource_id=str(target_user_id), status="success",
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()  # audit logging must never break the actual request


@admin_bp.route("/users/<int:user_id>", methods=["DELETE"])
@super_admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return jsonify({"message": "User deleted"}), 200


# ─── Database backups ────────────────────────────────────────────────────────
# A daily scheduled job (register_backup_job, app/__init__.py) already
# creates these automatically — this is the admin-facing on-demand
# trigger + visibility into what's on disk, not a replacement for the
# schedule.

@admin_bp.route("/backups", methods=["GET"])
@admin_required
def list_backups():
    from app.services.backup.db_backup import _BACKUP_DIR
    if not _BACKUP_DIR.exists():
        return jsonify({"backups": []}), 200
    files = sorted(_BACKUP_DIR.glob("smarttrade_*.db.gz"), key=lambda f: f.stat().st_mtime, reverse=True)
    return jsonify({"backups": [
        {"filename": f.name, "size_mb": round(f.stat().st_size / 1e6, 2),
         "created_at": datetime.utcfromtimestamp(f.stat().st_mtime).isoformat()}
        for f in files
    ]}), 200


@admin_bp.route("/backups/run", methods=["POST"])
@super_admin_required
def run_backup_now():
    from flask import current_app
    from app.services.backup.db_backup import create_backup
    path = create_backup(current_app._get_current_object())
    if not path:
        return jsonify({"error": "Backup failed or not applicable (non-SQLite database, or source file not found) — check server logs"}), 500
    return jsonify({"message": "Backup created", "path": path}), 201


# ─── API Configurations ──────────────────────────────────────────────────────

@admin_bp.route("/api-configs", methods=["GET"])
@admin_required
def list_api_configs():
    market = request.args.get("market")
    query  = APIConfig.query
    if market:
        query = query.filter_by(market=market)
    configs = query.order_by(APIConfig.market, APIConfig.priority.desc(), APIConfig.name).all()
    # Group by market
    grouped = {}
    for c in configs:
        mk = c.market or "other"
        grouped.setdefault(mk, []).append(c.to_dict())
    return jsonify({"configs": [c.to_dict() for c in configs], "grouped": grouped}), 200


@admin_bp.route("/api-configs/<int:cfg_id>", methods=["GET"])
@admin_required
def get_api_config(cfg_id):
    c = APIConfig.query.get_or_404(cfg_id)
    return jsonify(c.to_dict()), 200


@admin_bp.route("/api-configs", methods=["POST"])
@super_admin_required
def create_api_config():
    data = request.get_json() or {}
    required = ["name", "provider", "market"]
    if not all(k in data for k in required):
        return jsonify({"error": "name, provider and market are required"}), 400

    # Enforce unique name
    if APIConfig.query.filter_by(name=data["name"]).first():
        return jsonify({"error": f"A config named '{data['name']}' already exists"}), 409

    # If set as default, unset others in same market
    if data.get("is_default"):
        APIConfig.query.filter_by(market=data["market"], is_default=True).update({"is_default": False})

    cfg = APIConfig(
        name             = data["name"],
        provider         = data["provider"],
        market           = data["market"],
        base_url         = data.get("base_url", ""),
        websocket_url    = data.get("websocket_url", ""),
        auth_type        = data.get("auth_type", "api_key"),
        access_token     = data.get("access_token", ""),
        refresh_token    = data.get("refresh_token", ""),
        rate_limit       = int(data.get("rate_limit", 60)),
        refresh_interval = int(data.get("refresh_interval", 60)),
        priority         = int(data.get("priority", 0)),
        is_default       = bool(data.get("is_default", False)),
        is_active        = True,
        status           = "active",
    )
    if data.get("api_key"):    cfg.set_api_key(data["api_key"])
    if data.get("api_secret"): cfg.set_api_secret(data["api_secret"])
    db.session.add(cfg)
    db.session.commit()
    return jsonify(cfg.to_dict()), 201


@admin_bp.route("/api-configs/<int:cfg_id>", methods=["PUT"])
@super_admin_required
def update_api_config(cfg_id):
    cfg  = APIConfig.query.get_or_404(cfg_id)
    data = request.get_json() or {}

    field_map = {
        "name": "name", "provider": "provider", "market": "market",
        "base_url": "base_url", "websocket_url": "websocket_url",
        "auth_type": "auth_type", "rate_limit": "rate_limit",
        "refresh_interval": "refresh_interval", "priority": "priority",
        "is_default": "is_default", "is_active": "is_active", "status": "status",
    }
    for k, attr in field_map.items():
        if k in data:
            setattr(cfg, attr, data[k])

    # Clear other configs' is_default AFTER applying field_map above — if the
    # request also changes `market` in the same call, this must use the NEW
    # market (cfg.market, now updated) so the uniqueness clear targets the
    # market this config is actually moving into. Previously ran before the
    # field_map loop, using the OLD market, which could leave two configs
    # marked is_default=True in the new market (the moved one, plus whatever
    # was already default there) — ambiguous "default" resolution for
    # whichever fetcher code does .filter_by(is_default=True).first().
    if "is_default" in data and data["is_default"]:
        APIConfig.query.filter(
            APIConfig.market == cfg.market,
            APIConfig.id != cfg_id,
            APIConfig.is_default
        ).update({"is_default": False})

    # Only update credentials if supplied
    if data.get("api_key"):    cfg.set_api_key(data["api_key"])
    if data.get("api_secret"): cfg.set_api_secret(data["api_secret"])
    if data.get("access_token"):  cfg.access_token  = data["access_token"]
    if data.get("refresh_token"): cfg.refresh_token = data["refresh_token"]

    cfg.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(cfg.to_dict()), 200


@admin_bp.route("/api-configs/<int:cfg_id>", methods=["DELETE"])
@super_admin_required
def delete_api_config(cfg_id):
    cfg = APIConfig.query.get_or_404(cfg_id)
    db.session.delete(cfg)
    db.session.commit()
    return jsonify({"message": f"'{cfg.name}' deleted"}), 200


@admin_bp.route("/api-configs/<int:cfg_id>/pause", methods=["POST"])
@super_admin_required
def pause_api_config(cfg_id):
    cfg = APIConfig.query.get_or_404(cfg_id)
    cfg.status    = "paused"
    cfg.is_active = False
    cfg.updated_at = datetime.utcnow()
    db.session.commit()
    from app.services.data.fetcher import invalidate_blocked_markets_cache
    invalidate_blocked_markets_cache()
    _log(cfg_id, "pause", "ok")
    return jsonify({"message": f"'{cfg.name}' paused", "status": "paused"}), 200


@admin_bp.route("/api-configs/<int:cfg_id>/resume", methods=["POST"])
@super_admin_required
def resume_api_config(cfg_id):
    cfg = APIConfig.query.get_or_404(cfg_id)
    cfg.status     = "active"
    cfg.is_active  = True
    cfg.error_count = 0
    cfg.updated_at = datetime.utcnow()
    db.session.commit()
    from app.services.data.fetcher import invalidate_blocked_markets_cache
    invalidate_blocked_markets_cache()
    _log(cfg_id, "resume", "ok")
    return jsonify({"message": f"'{cfg.name}' resumed", "status": "active"}), 200


@admin_bp.route("/api-configs/<int:cfg_id>/set-default", methods=["POST"])
@super_admin_required
def set_default_api_config(cfg_id):
    cfg = APIConfig.query.get_or_404(cfg_id)
    APIConfig.query.filter(
        APIConfig.market == cfg.market,
        APIConfig.is_default
    ).update({"is_default": False})
    cfg.is_default = True
    db.session.commit()
    return jsonify({"message": f"'{cfg.name}' set as default for {cfg.market}"}), 200


@admin_bp.route("/api-configs/<int:cfg_id>/duplicate", methods=["POST"])
@super_admin_required
def duplicate_api_config(cfg_id):
    src = APIConfig.query.get_or_404(cfg_id)
    new_name = f"{src.name} (copy)"
    # ensure unique
    counter = 1
    while APIConfig.query.filter_by(name=new_name).first():
        counter += 1
        new_name = f"{src.name} (copy {counter})"
    dup = APIConfig(
        name=new_name, provider=src.provider, market=src.market,
        base_url=src.base_url, websocket_url=src.websocket_url,
        auth_type=src.auth_type, api_key_encrypted=src.api_key_encrypted,
        api_secret_encrypted=src.api_secret_encrypted,
        access_token=src.access_token, refresh_token=src.refresh_token,
        rate_limit=src.rate_limit, refresh_interval=src.refresh_interval,
        priority=src.priority, is_default=False, is_active=False, status="paused",
    )
    db.session.add(dup)
    db.session.commit()
    return jsonify(dup.to_dict()), 201


@admin_bp.route("/api-configs/<int:cfg_id>/test", methods=["POST"])
@super_admin_required
def test_api_config(cfg_id):
    cfg = APIConfig.query.get_or_404(cfg_id)
    result = _test_connection(cfg)
    # Update connection_status in DB
    cfg.connection_status = "ok" if result["success"] else "error"
    cfg.last_latency_ms   = result.get("latency_ms")
    if result["success"]:
        cfg.last_sync = datetime.utcnow()
        cfg.error_count = 0
    else:
        cfg.error_count = (cfg.error_count or 0) + 1
    db.session.commit()
    _log(cfg_id, "test", "ok" if result["success"] else "error",
         response_time_ms=result.get("latency_ms"), error_message=result.get("error"))
    return jsonify(result), 200


@admin_bp.route("/api-configs/<int:cfg_id>/logs", methods=["GET"])
@admin_required
def get_api_logs(cfg_id):
    APIConfig.query.get_or_404(cfg_id)
    logs = APILog.query.filter_by(api_config_id=cfg_id) \
        .order_by(APILog.created_at.desc()).limit(50).all()
    return jsonify({"logs": [l.to_dict() for l in logs]}), 200


@admin_bp.route("/api-configs/providers", methods=["GET"])
@admin_required
def get_providers():
    return jsonify({"providers": APIConfig.PROVIDERS, "defaults": APIConfig.PROVIDER_DEFAULTS}), 200


# ─── Audit / System Logs ────────────────────────────────────────────────────

@admin_bp.route("/audit-logs", methods=["GET"])
@admin_required
def audit_logs():
    page = int(request.args.get("page", 1))
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()) \
        .paginate(page=page, per_page=50, error_out=False)
    return jsonify({"logs": [l.to_dict() for l in logs.items], "total": logs.total, "pages": logs.pages}), 200


@admin_bp.route("/audit-logs", methods=["DELETE"])
@super_admin_required
def clear_audit_logs():
    deleted = AuditLog.query.delete()
    db.session.commit()
    return jsonify({"message": f"Cleared {deleted} audit log entries"}), 200


@admin_bp.route("/brokers", methods=["GET"])
@admin_required
def list_brokers():
    brokers = Broker.query.order_by(Broker.sort_order, Broker.name).all()
    return jsonify({"brokers": [b.to_dict() for b in brokers]}), 200


@admin_bp.route("/brokers", methods=["POST"])
@super_admin_required
def create_broker():
    data = request.get_json() or {}
    if not data.get("name"):
        return jsonify({"error": "name is required"}), 400
    if Broker.query.filter_by(name=data["name"]).first():
        return jsonify({"error": f"A broker named '{data['name']}' already exists"}), 409

    broker = Broker(
        name=data["name"],
        referral_link=data.get("referral_link"),
        is_active=data.get("is_active", True),
        sort_order=data.get("sort_order", 0),
    )
    db.session.add(broker)
    db.session.commit()
    return jsonify(broker.to_dict()), 201


@admin_bp.route("/brokers/<int:broker_id>", methods=["PUT"])
@super_admin_required
def update_broker(broker_id):
    broker = Broker.query.get_or_404(broker_id)
    data = request.get_json() or {}

    field_map = ["name", "referral_link", "is_active", "sort_order"]
    for k in field_map:
        if k in data:
            setattr(broker, k, data[k])

    db.session.commit()
    return jsonify(broker.to_dict()), 200


@admin_bp.route("/brokers/<int:broker_id>", methods=["DELETE"])
@super_admin_required
def delete_broker(broker_id):
    broker = Broker.query.get_or_404(broker_id)
    # Don't hard-delete a broker users already reference — deactivate instead
    # so existing users' broker selection stays intact and the dropdown just
    # stops offering it to new signups.
    if broker.users.count() > 0:
        broker.is_active = False
        db.session.commit()
        return jsonify({"message": f"'{broker.name}' has existing users — deactivated instead of deleted"}), 200

    db.session.delete(broker)
    db.session.commit()
    return jsonify({"message": f"'{broker.name}' deleted"}), 200


@admin_bp.route("/referral-codes", methods=["GET"])
@admin_required
def list_referral_codes():
    # Safety cap, not a normal-operation constraint — referral codes are
    # created manually by admins, so this table stays small in practice.
    codes = ReferralCode.query.order_by(ReferralCode.created_at.desc()).limit(1000).all()
    return jsonify({"referral_codes": [{
        "id": c.id,
        "code": c.code,
        "broker_name": c.broker_name,
        "description": c.description,
        "referred_role": c.referred_role.name if c.referred_role else None,
        "referred_subscription": c.referred_subscription.name if c.referred_subscription else None,
        "is_active": c.is_active,
        "max_uses": c.max_uses,
        "uses_count": c.uses_count,
        "expires_at": c.expires_at.isoformat() if c.expires_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    } for c in codes]}), 200


@admin_bp.route("/referral-codes", methods=["POST"])
@super_admin_required
def create_referral_code():
    data = request.get_json() or {}
    code = (data.get("code") or "").strip().upper()
    if not code:
        return jsonify({"error": "code is required"}), 400
    if ReferralCode.query.filter_by(code=code).first():
        return jsonify({"error": f"Referral code '{code}' already exists"}), 409

    sub_name = data.get("referred_subscription", "premium")
    sub = Subscription.query.filter_by(name=sub_name).first()
    role = Role.query.filter_by(name=sub_name).first()
    if not sub:
        return jsonify({"error": f"Unknown subscription plan '{sub_name}'"}), 400

    rc = ReferralCode(
        code=code,
        broker_name=data.get("broker_name"),
        description=data.get("description"),
        referred_role_id=role.id if role else None,
        referred_subscription_id=sub.id,
        is_active=data.get("is_active", True),
        max_uses=data.get("max_uses"),
    )
    db.session.add(rc)
    db.session.commit()
    return jsonify({"id": rc.id, "code": rc.code}), 201


@admin_bp.route("/referral-codes/<int:code_id>", methods=["PUT"])
@super_admin_required
def update_referral_code(code_id):
    rc = ReferralCode.query.get_or_404(code_id)
    data = request.get_json() or {}
    for k in ["broker_name", "description", "is_active", "max_uses"]:
        if k in data:
            setattr(rc, k, data[k])
    db.session.commit()
    return jsonify({"message": f"'{rc.code}' updated"}), 200


@admin_bp.route("/referral-codes/<int:code_id>", methods=["DELETE"])
@super_admin_required
def delete_referral_code(code_id):
    rc = ReferralCode.query.get_or_404(code_id)
    db.session.delete(rc)
    db.session.commit()
    return jsonify({"message": f"'{rc.code}' deleted"}), 200


@admin_bp.route("/system-logs", methods=["GET"])
@admin_required
def system_logs():
    page  = int(request.args.get("page", 1))
    level = request.args.get("level")
    query = SystemLog.query
    if level:
        query = query.filter_by(level=level.upper())
    logs = query.order_by(SystemLog.created_at.desc()) \
        .paginate(page=page, per_page=50, error_out=False)
    return jsonify({"logs": [l.to_dict() for l in logs.items], "total": logs.total}), 200


@admin_bp.route("/system-logs", methods=["DELETE"])
@super_admin_required
def clear_system_logs():
    """Bulk-delete system logs — optionally scoped to a level (matches the
    page's existing filter), otherwise clears everything."""
    level = request.args.get("level")
    query = SystemLog.query
    if level:
        query = query.filter_by(level=level.upper())
    deleted = query.delete(synchronize_session=False)
    db.session.commit()
    return jsonify({"deleted": deleted}), 200


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _log(cfg_id, action, status, response_time_ms=None, error_message=None):
    try:
        entry = APILog(api_config_id=cfg_id, action=action, status=status,
                       response_time_ms=response_time_ms, error_message=error_message)
        db.session.add(entry)
        db.session.commit()
    except Exception:
        pass


def _test_connection(cfg: APIConfig) -> dict:
    """Best-effort connectivity check. Returns structured result dict."""
    result = {
        "success": False, "auth_ok": False, "reachable": False,
        "market_data_ok": False, "latency_ms": None,
        "server_time": None, "error": None, "details": {},
    }
    base = (cfg.base_url or "").rstrip("/")
    if not base:
        result["error"] = "No base URL configured"
        return result

    headers = {}
    if cfg.auth_type == "api_key" and cfg.api_key_encrypted:
        api_key = cfg.get_api_key()
        if api_key:
            headers["X-MBX-APIKEY"] = api_key   # Binance style
            headers["X-API-KEY"]    = api_key
    if cfg.auth_type == "token" and cfg.access_token:
        headers["Authorization"] = f"Bearer {cfg.access_token}"

    # Provider-specific ping endpoints
    ping_paths = {
        "binance":       "/api/v3/time",
        "delta_exchange": "/v2/products?page_size=1",
        "bybit":         "/v5/market/time",
        "okx":           "/api/v5/public/time",
        "kucoin":        "/api/v1/timestamp",
        "angel_one":     "/rest/secure/angelbroking/user/v1/getProfile",
        "zerodha":       "/",
        "upstox":        "/v2/market-quote/ltp",
        "yahoo":         "/v1/finance/search?q=AAPL&quotesCount=1&newsCount=0",
        "alpha_vantage": "/query?function=TIME_SERIES_INTRADAY&symbol=IBM&interval=5min",
        "twelve_data":   "/time_series?symbol=AAPL&interval=1min&outputsize=1",
        "finnhub":       "/quote?symbol=AAPL",
        "polygon":       "/v2/aggs/ticker/AAPL/range/1/day/2023-01-01/2023-01-02",
        "alpaca":        "/v2/clock",
    }
    path = ping_paths.get(cfg.provider, "/")
    url  = base + path

    try:
        t0  = time.time()
        # Was previously passing cfg.api_key_encrypted — the raw ciphertext
        # blob, not the decrypted key — which meant this connectivity test
        # always failed auth for these three providers, and additionally
        # sent encrypted secret material out over the wire/query-string to
        # a third party for no reason.
        r   = requests.get(url, headers=headers, timeout=6,
                           params={"apikey": cfg.get_api_key()} if cfg.provider in ("alpha_vantage", "finnhub", "twelve_data") else {})
        ms  = int((time.time() - t0) * 1000)
        result["latency_ms"] = ms
        result["reachable"]  = True

        if r.status_code in (200, 201):
            result["auth_ok"]       = True
            result["market_data_ok"]= True
            result["success"]       = True
            # Try to extract server time
            try:
                j = r.json()
                result["server_time"] = (
                    j.get("serverTime") or j.get("time") or
                    j.get("data", {}).get("serverTime") if isinstance(j.get("data"), dict) else None
                )
                result["details"] = {"status_code": r.status_code}
            except Exception:
                pass
        elif r.status_code == 401:
            result["reachable"]  = True
            result["error"]      = "Authentication failed — check API key/secret"
        elif r.status_code == 403:
            result["reachable"]  = True
            result["error"]      = "Forbidden — IP not whitelisted or permissions missing"
        else:
            result["error"] = f"HTTP {r.status_code}"
    except requests.exceptions.ConnectionError:
        result["error"] = "Cannot reach server — check base URL or network"
    except requests.exceptions.Timeout:
        result["error"] = "Connection timed out (>6s)"
    except Exception as e:
        result["error"] = str(e)

    return result
