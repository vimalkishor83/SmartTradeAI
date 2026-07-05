"""System health & readiness endpoints.

- ``/api/v1/system/health`` — liveness: the process is up and serving.
- ``/api/v1/system/ready``  — readiness: dependencies are usable (DB reachable,
  scheduler running, market-data stream alive). Returns 503 if any hard
  dependency is down, so an orchestrator / uptime monitor can react.

Both are unauthenticated on purpose (probes must work without a session) but
expose no sensitive data.
"""
import logging
import time
from datetime import datetime, timezone

from flask import Blueprint, jsonify
from sqlalchemy import text

from app.extensions import db, scheduler

logger = logging.getLogger(__name__)

system_bp = Blueprint("system", __name__)

# Process start time (module import ~ app boot) for a simple uptime figure.
_START_TS = time.time()


@system_bp.route("/health", methods=["GET"])
def health():
    """Liveness probe — always cheap, never touches dependencies."""
    return jsonify({
        "status": "alive",
        "service": "smarttradeai",
        "uptime_seconds": round(time.time() - _START_TS, 1),
        "time": datetime.now(timezone.utc).isoformat(),
    }), 200


def _check_database() -> dict:
    try:
        db.session.execute(text("SELECT 1"))
        return {"name": "database", "healthy": True, "detail": db.engine.dialect.name}
    except Exception as e:
        logger.warning(f"readiness: database check failed: {e}")
        return {"name": "database", "healthy": False, "detail": "unreachable"}


def _check_scheduler() -> dict:
    try:
        running = bool(getattr(scheduler, "running", False))
        jobs = len(scheduler.get_jobs()) if running else 0
        return {"name": "scheduler", "healthy": running, "detail": f"{jobs} jobs"}
    except Exception as e:
        logger.warning(f"readiness: scheduler check failed: {e}")
        return {"name": "scheduler", "healthy": False, "detail": "error"}


def _check_market_stream() -> dict:
    # Best-effort: the Delta Exchange WS stream is a soft dependency (non-crypto
    # markets poll instead), so a down stream is reported but not fatal.
    try:
        from app.services.data.delta_stream import delta_stream
        running = bool(getattr(delta_stream, "running", None) or
                       getattr(delta_stream, "_running", False))
        return {"name": "market_stream", "healthy": True,
                "detail": "connected" if running else "idle (polling fallback)"}
    except Exception as e:
        logger.debug(f"readiness: market stream check failed: {e}")
        return {"name": "market_stream", "healthy": True, "detail": "unknown"}


@system_bp.route("/ready", methods=["GET"])
def ready():
    """Readiness probe — 200 only if all HARD dependencies are healthy."""
    checks = [_check_database(), _check_scheduler(), _check_market_stream()]
    # Only database + scheduler are hard requirements; market stream is soft.
    hard = {"database", "scheduler"}
    ready_ = all(c["healthy"] for c in checks if c["name"] in hard)
    payload = {
        "status": "ready" if ready_ else "not_ready",
        "checks": checks,
        "time": datetime.now(timezone.utc).isoformat(),
    }
    return jsonify(payload), (200 if ready_ else 503)
