"""Tests for the side-effect-free provider verification health contract."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.provider_health import summarize_provider_health


def _config(**overrides):
    values = {
        "status": "active",
        "connection_status": "ok",
        "last_sync": None,
        "refresh_interval": 60,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_unverified_provider_is_explicitly_untested():
    health = summarize_provider_health(_config(), now=datetime(2026, 9, 6))

    assert health["state"] == "UNTESTED"
    assert health["label"] == "Not verified"
    assert health["last_verified_at"] is None


def test_recent_success_is_healthy():
    now = datetime(2026, 9, 6, 12, 0)
    health = summarize_provider_health(
        _config(last_sync=now - timedelta(minutes=10)), now=now,
    )

    assert health["state"] == "HEALTHY"
    assert health["age_seconds"] == 600
    assert health["stale_after_seconds"] == 900


def test_old_success_is_stale_using_refresh_interval():
    now = datetime(2026, 9, 6, 12, 0)
    health = summarize_provider_health(
        _config(last_sync=now - timedelta(minutes=31), refresh_interval=600), now=now,
    )

    assert health["state"] == "STALE"
    assert health["stale_after_seconds"] == 1800
    assert health["age_seconds"] == 1860


def test_paused_and_failed_statuses_take_priority_over_freshness():
    now = datetime(2026, 9, 6, 12, 0)
    last_sync = now - timedelta(minutes=1)

    assert summarize_provider_health(
        _config(status="paused", last_sync=last_sync), now=now,
    )["state"] == "PAUSED"
    assert summarize_provider_health(
        _config(connection_status="error", last_sync=last_sync), now=now,
    )["state"] == "ERROR"


def test_aware_database_timestamp_does_not_raise():
    now = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
    health = summarize_provider_health(
        _config(last_sync=now - timedelta(minutes=5)), now=now,
    )

    assert health["state"] == "HEALTHY"
    assert health["age_seconds"] == 300


def test_api_config_serialization_includes_health_contract(app):
    with app.app_context():
        from app.models.api_config import APIConfig

        config = APIConfig(
            name="Serialization check",
            status="active",
            connection_status="unknown",
        )
        payload = config.to_dict()

    assert payload["health"]["state"] == "UNTESTED"
    assert payload["health"]["last_verified_at"] is None
