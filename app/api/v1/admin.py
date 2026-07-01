import time
import psutil
import requests
from flask import Blueprint, request, jsonify
from app.extensions import db
from app.models.user import User, Role, Subscription
from app.models.asset import Asset
from app.models.api_config import APIConfig, APILog
from app.models.audit import AuditLog, SystemLog
from app.models.signal import Signal, SignalHistory
from app.auth.decorators import admin_required
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
        "users":   {"total": total_users, "active": active_users},
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


# ─── Users ──────────────────────────────────────────────────────────────────

@admin_bp.route("/users", methods=["GET"])
@admin_required
def list_users():
    page   = int(request.args.get("page", 1))
    search = request.args.get("search", "")
    query  = User.query
    if search:
        query = query.filter(
            User.username.ilike(f"%{search}%") | User.email.ilike(f"%{search}%")
        )
    users = query.order_by(User.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return jsonify({"users": [u.to_dict() for u in users.items], "total": users.total, "pages": users.pages}), 200


@admin_bp.route("/users/<int:user_id>", methods=["PUT"])
@admin_required
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    for f in ["is_active", "role_id", "subscription_id", "is_verified"]:
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
@admin_required
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
        api_key_encrypted    = data.get("api_key", ""),
        api_secret_encrypted = data.get("api_secret", ""),
        access_token     = data.get("access_token", ""),
        refresh_token    = data.get("refresh_token", ""),
        rate_limit       = int(data.get("rate_limit", 60)),
        refresh_interval = int(data.get("refresh_interval", 60)),
        priority         = int(data.get("priority", 0)),
        is_default       = bool(data.get("is_default", False)),
        is_active        = True,
        status           = "active",
    )
    db.session.add(cfg)
    db.session.commit()
    return jsonify(cfg.to_dict()), 201


@admin_bp.route("/api-configs/<int:cfg_id>", methods=["PUT"])
@admin_required
def update_api_config(cfg_id):
    cfg  = APIConfig.query.get_or_404(cfg_id)
    data = request.get_json() or {}

    if "is_default" in data and data["is_default"]:
        APIConfig.query.filter(
            APIConfig.market == cfg.market,
            APIConfig.id != cfg_id,
            APIConfig.is_default
        ).update({"is_default": False})

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

    # Only update credentials if supplied
    if data.get("api_key"):    cfg.api_key_encrypted    = data["api_key"]
    if data.get("api_secret"): cfg.api_secret_encrypted = data["api_secret"]
    if data.get("access_token"):  cfg.access_token  = data["access_token"]
    if data.get("refresh_token"): cfg.refresh_token = data["refresh_token"]

    cfg.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(cfg.to_dict()), 200


@admin_bp.route("/api-configs/<int:cfg_id>", methods=["DELETE"])
@admin_required
def delete_api_config(cfg_id):
    cfg = APIConfig.query.get_or_404(cfg_id)
    db.session.delete(cfg)
    db.session.commit()
    return jsonify({"message": f"'{cfg.name}' deleted"}), 200


@admin_bp.route("/api-configs/<int:cfg_id>/pause", methods=["POST"])
@admin_required
def pause_api_config(cfg_id):
    cfg = APIConfig.query.get_or_404(cfg_id)
    cfg.status    = "paused"
    cfg.is_active = False
    cfg.updated_at = datetime.utcnow()
    db.session.commit()
    _log(cfg_id, "pause", "ok")
    return jsonify({"message": f"'{cfg.name}' paused", "status": "paused"}), 200


@admin_bp.route("/api-configs/<int:cfg_id>/resume", methods=["POST"])
@admin_required
def resume_api_config(cfg_id):
    cfg = APIConfig.query.get_or_404(cfg_id)
    cfg.status     = "active"
    cfg.is_active  = True
    cfg.error_count = 0
    cfg.updated_at = datetime.utcnow()
    db.session.commit()
    _log(cfg_id, "resume", "ok")
    return jsonify({"message": f"'{cfg.name}' resumed", "status": "active"}), 200


@admin_bp.route("/api-configs/<int:cfg_id>/set-default", methods=["POST"])
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
def clear_audit_logs():
    deleted = AuditLog.query.delete()
    db.session.commit()
    return jsonify({"message": f"Cleared {deleted} audit log entries"}), 200


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
        headers["X-MBX-APIKEY"] = cfg.api_key_encrypted   # Binance style
        headers["X-API-KEY"]    = cfg.api_key_encrypted
    if cfg.auth_type == "token" and cfg.access_token:
        headers["Authorization"] = f"Bearer {cfg.access_token}"

    # Provider-specific ping endpoints
    ping_paths = {
        "binance":       "/api/v3/time",
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
        r   = requests.get(url, headers=headers, timeout=6,
                           params={"apikey": cfg.api_key_encrypted} if cfg.provider in ("alpha_vantage", "finnhub", "twelve_data") else {})
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
