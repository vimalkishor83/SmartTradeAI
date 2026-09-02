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

from flask import Blueprint, jsonify, current_app
from sqlalchemy import text

from app.extensions import db, scheduler, cache, limiter

logger = logging.getLogger(__name__)

system_bp = Blueprint("system", __name__)
# Liveness/readiness probes are hit constantly by infrastructure (Docker's
# own healthcheck polls /ready every 30s from the container's fixed
# 127.0.0.1 identity, forever, for the container's entire lifetime) and the
# rate limiter's counters are Redis-backed so they persist across container
# restarts — meaning repeated restarts within the same rolling window keep
# adding to the same 127.0.0.1 bucket rather than resetting. Left unexempted,
# that bucket eventually exceeds the per-hour/per-day default limits purely
# from the healthcheck's own routine traffic, Docker starts seeing 429s
# instead of 200s, and marks an otherwise perfectly healthy container
# "unhealthy" — a purely self-inflicted false alarm.
limiter.exempt(system_bp)

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
    # A web worker running with RUN_SCHEDULER=0 is SUPPOSED to have no
    # scheduler — background jobs belong to the dedicated worker process.
    # Reporting that as unhealthy would mark every web replica permanently
    # unready and pull them all out of the load balancer.
    from app import run_background_work
    if not run_background_work():
        return {"name": "scheduler", "healthy": True, "detail": "not in this process (RUN_SCHEDULER=0)"}
    try:
        running = bool(getattr(scheduler, "running", False))
        jobs = len(scheduler.get_jobs()) if running else 0
        return {"name": "scheduler", "healthy": running, "detail": f"{jobs} jobs"}
    except Exception as e:
        logger.warning(f"readiness: scheduler check failed: {e}")
        return {"name": "scheduler", "healthy": False, "detail": "error"}


def _check_redis() -> dict:
    """Redis is a hard dependency only when the app is actually configured to
    use it (CACHE_TYPE=RedisCache). In that mode the cache AND the rate limiter
    both live in Redis, so an unreachable Redis means degraded correctness —
    not just a slower cache — and readiness should reflect that. On
    SimpleCache deployments this reports healthy/not-applicable so the
    single-process LAN deployment isn't marked unready for a service it never
    uses.
    """
    if current_app.config.get("CACHE_TYPE") != "RedisCache":
        return {"name": "redis", "healthy": True, "detail": "not in use (SimpleCache)"}
    try:
        # Round-trip through the configured cache client rather than opening a
        # second connection, so this validates the exact client the app uses.
        cache.set("_readiness_probe", "1", timeout=10)
        ok = cache.get("_readiness_probe") == "1"
        return {"name": "redis", "healthy": ok, "detail": "reachable" if ok else "read-back failed"}
    except Exception as e:
        logger.warning(f"readiness: redis check failed: {e}")
        return {"name": "redis", "healthy": False, "detail": "unreachable"}


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
    checks = [_check_database(), _check_scheduler(), _check_redis(), _check_market_stream()]
    # Database, scheduler and (when configured) Redis are hard requirements;
    # the market stream is soft. _check_redis self-reports healthy when the
    # deployment isn't using Redis at all.
    hard = {"database", "scheduler", "redis"}
    ready_ = all(c["healthy"] for c in checks if c["name"] in hard)
    payload = {
        "status": "ready" if ready_ else "not_ready",
        "checks": checks,
        "time": datetime.now(timezone.utc).isoformat(),
    }
    return jsonify(payload), (200 if ready_ else 503)
