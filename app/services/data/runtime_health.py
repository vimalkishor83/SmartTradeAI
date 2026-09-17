"""Process-local market-provider runtime health telemetry.

This is deliberately observational: it records fetch outcomes in memory and
never changes provider selection, cached market data, or trading behaviour.
The database-backed provider verification contract remains separate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
import time


_lock = Lock()
_providers: dict[str, dict] = {}


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def record_success(provider: str, *, latency_ms: float | None = None) -> None:
    """Record a successful upstream request without retaining response data."""
    now = time.time()
    with _lock:
        state = _providers.setdefault(provider, {"consecutive_failures": 0})
        state.update({
            "last_success_ts": now,
            "last_latency_ms": round(float(latency_ms), 1) if latency_ms is not None else None,
            "consecutive_failures": 0,
            "last_error": None,
        })


def record_failure(provider: str, *, reason: str = "provider request failed") -> None:
    """Record a sanitized failure reason; exception text is never exposed."""
    now = time.time()
    with _lock:
        state = _providers.setdefault(provider, {"consecutive_failures": 0})
        state.update({
            "last_failure_ts": now,
            "last_error": reason,
            "consecutive_failures": int(state.get("consecutive_failures", 0)) + 1,
        })


def snapshot(*, now: float | None = None, stale_after_seconds: int = 180) -> list[dict]:
    """Return safe, serializable provider telemetry for status surfaces."""
    now = time.time() if now is None else now
    with _lock:
        rows = {name: dict(state) for name, state in _providers.items()}

    result = []
    for provider, state in sorted(rows.items()):
        last_success_ts = state.get("last_success_ts")
        age = max(0, round(now - last_success_ts, 1)) if last_success_ts is not None else None
        failures = int(state.get("consecutive_failures", 0))
        if last_success_ts is None:
            health_state = "ERROR" if failures else "UNTESTED"
        elif age is not None and age > stale_after_seconds:
            health_state = "STALE"
        elif failures >= 3:
            health_state = "DEGRADED"
        else:
            health_state = "HEALTHY"
        result.append({
            "provider": provider,
            "state": health_state,
            "last_success_at": _iso(last_success_ts),
            "last_failure_at": _iso(state.get("last_failure_ts")),
            "age_seconds": age,
            "stale_after_seconds": stale_after_seconds,
            "last_latency_ms": state.get("last_latency_ms"),
            "consecutive_failures": failures,
            "last_error": state.get("last_error"),
        })
    return result


def reset() -> None:
    """Clear telemetry for isolated tests; runtime callers should not use it."""
    with _lock:
        _providers.clear()
