"""Small, side-effect-free health contract for admin provider displays."""

from datetime import datetime


def summarize_provider_health(config, now: datetime | None = None) -> dict:
    """Describe the freshness of the last successful provider verification.

    ``last_sync`` is written by the explicit admin connection test, so this
    contract deliberately calls it a verification rather than live provider
    telemetry. It never performs network I/O and remains safe for list views.
    """
    now = now or datetime.utcnow()
    status = (config.status or "unknown").lower()
    connection_status = (config.connection_status or "unknown").lower()
    last_sync = config.last_sync
    last_verified_at = last_sync.isoformat() if last_sync else None

    if status == "paused":
        return {
            "state": "PAUSED",
            "label": "Paused",
            "detail": "Provider is intentionally paused",
            "last_verified_at": last_verified_at,
            "age_seconds": None,
        }

    if status == "error" or connection_status == "error":
        return {
            "state": "ERROR",
            "label": "Connection error",
            "detail": "The last provider verification failed",
            "last_verified_at": last_verified_at,
            "age_seconds": _age_seconds(last_sync, now),
        }

    if last_sync is None:
        return {
            "state": "UNTESTED",
            "label": "Not verified",
            "detail": "Run a connection test to verify this provider",
            "last_verified_at": None,
            "age_seconds": None,
        }

    age_seconds = _age_seconds(last_sync, now)
    interval = max(int(config.refresh_interval or 60), 60)
    stale_after_seconds = max(interval * 3, 900)
    if age_seconds is not None and age_seconds > stale_after_seconds:
        return {
            "state": "STALE",
            "label": "Verification stale",
            "detail": "Run a new connection test before relying on this feed",
            "last_verified_at": last_verified_at,
            "age_seconds": age_seconds,
            "stale_after_seconds": stale_after_seconds,
        }

    return {
        "state": "HEALTHY",
        "label": "Recently verified",
        "detail": "Last connection verification succeeded",
        "last_verified_at": last_verified_at,
        "age_seconds": age_seconds,
        "stale_after_seconds": stale_after_seconds,
    }


def _age_seconds(value: datetime | None, now: datetime) -> int | None:
    if value is None:
        return None
    # Database timestamps are currently UTC-naive. Guard against a future
    # aware value so an admin list cannot fail on mixed timestamp sources.
    try:
        return max(0, int((now - value).total_seconds()))
    except TypeError:
        if value.tzinfo is not None and now.tzinfo is None:
            now = now.replace(tzinfo=value.tzinfo)
        elif value.tzinfo is None and now.tzinfo is not None:
            value = value.replace(tzinfo=now.tzinfo)
        return max(0, int((now - value).total_seconds()))
