"""Read-only market-data health contract for every frontend surface."""

from datetime import datetime, timezone


def _parse_iso(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # Naive verification timestamps are stored as UTC; give them a tzinfo
    # so they compare correctly against tz-aware runtime timestamps instead
    # of raising or silently mis-ordering under a raw string/`max()` compare.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed

from app.services.api_contracts import with_contract
from app.services.data.runtime_health import snapshot as runtime_health_snapshot
from app.services.provider_health import summarize_provider_health


def build_market_health_snapshot(now=None):
    """Build a sanitized snapshot without making provider network calls.

    Provider ``last_sync`` is explicitly described as verification time. This
    prevents an admin connection test from being presented as a live tick.
    """
    from app.models.api_config import APIConfig
    from app.models.asset import Asset

    now = now or datetime.utcnow()
    active_assets = Asset.query.filter_by(is_active=True).count()
    configs = (APIConfig.query.filter_by(is_active=True)
               .order_by(APIConfig.priority.desc(), APIConfig.id.asc()).all())

    runtime_by_provider = {r["provider"]: r for r in runtime_health_snapshot()}

    providers = []
    for config in configs:
        health = summarize_provider_health(config, now=now)
        runtime = runtime_by_provider.get(config.provider)
        # A stale or failed admin *verification* doesn't mean the feed is
        # actually down -- live fetches happen continuously regardless of
        # whether anyone has re-run the manual connection test. If the
        # process has recorded a recent successful fetch for this exact
        # provider, that live signal is more trustworthy than a
        # verification record that can go stale for weeks at a time.
        live_state = health.get("state")
        if live_state in {"ERROR", "STALE"} and runtime and runtime["state"] == "HEALTHY":
            live_state = "HEALTHY"
        providers.append({
            "provider": config.provider or config.name,
            "market": config.market,
            "state": health.get("state"),
            "live_state": live_state,
            "label": health.get("label"),
            "detail": health.get("detail"),
            "last_verified_at": health.get("last_verified_at"),
            "age_seconds": health.get("age_seconds"),
            "stale_after_seconds": health.get("stale_after_seconds"),
            "last_latency_ms": config.last_latency_ms,
            "error_count": int(config.error_count or 0),
        })

    healthy = [p for p in providers if p["live_state"] == "HEALTHY"]
    errors = [p for p in providers if p["live_state"] in {"ERROR", "STALE"}]
    if not active_assets:
        status = "unavailable"
        reason = "No active assets are configured"
    elif not providers:
        status = "degraded"
        reason = "No active market-data provider is configured"
    elif not healthy:
        status = "unavailable"
        reason = errors[0]["detail"] if errors else "No provider has a recent verification"
    elif errors:
        status = "degraded"
        reason = f"{len(errors)} provider(s) need attention"
    else:
        status = "ready"
        reason = "At least one active provider is recently verified"

    # Prefer live fetch timestamps over verification timestamps when both
    # exist -- "last_update" is meant to answer "when did we last actually
    # get data", and a live successful fetch answers that more accurately
    # than a manual connection test that may not have been re-run in weeks.
    candidate_timestamps = [
        _parse_iso(r.get("last_success_at")) for r in runtime_by_provider.values()
    ] + [_parse_iso(p["last_verified_at"]) for p in providers]
    latest_dt = max((ts for ts in candidate_timestamps if ts is not None), default=None)
    latest = latest_dt.isoformat() if latest_dt else None
    freshness = {
        "state": status,
        "label": {"ready": "Fresh", "degraded": "Degraded", "unavailable": "Unavailable"}[status],
        "reason": reason,
        "last_update": latest,
    }
    payload = {
        "status": status,
        "reason": reason,
        "active_assets": active_assets,
        "provider_count": len(providers),
        "providers": providers,
        "last_update": latest,
        "freshness": freshness,
        "runtime": {
            "providers": runtime_health_snapshot(),
            "description": "Process-local fetch telemetry; cached responses do not refresh this timestamp.",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return with_contract(payload, source="provider_verification", freshness=freshness)
