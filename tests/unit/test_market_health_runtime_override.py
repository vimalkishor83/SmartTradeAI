"""Regression coverage for the provider-verification vs runtime-health
mismatch: a provider whose stored connection test is stale/failed but
whose process has recorded a recent live successful fetch must not be
reported as broken overall -- see app/services/market_health.py."""

from app.services.data import runtime_health
from app.services.market_health import build_market_health_snapshot


def _make_config(app, *, provider, market, status="error", connection_status="error", last_sync=None):
    from app.extensions import db
    from app.models.api_config import APIConfig

    config = APIConfig(
        name=f"{provider}-{market}", provider=provider, market=market,
        is_active=True, status=status, connection_status=connection_status,
        last_sync=last_sync, error_count=3,
    )
    db.session.add(config)
    db.session.commit()
    return config


def test_live_success_overrides_a_stale_failed_verification(app):
    with app.app_context():
        from app.models.asset import Asset
        from app.extensions import db
        from app.models.api_config import APIConfig

        # Isolate from _seed_initial_data()'s own "Delta Exchange India
        # (Crypto)" row, which would otherwise also match provider ==
        # "delta_exchange" and make `next(...)` pick an arbitrary one.
        APIConfig.query.filter_by(provider="delta_exchange").delete()
        db.session.add(Asset(symbol="BTCUSDT", name="Bitcoin", market="crypto", is_active=True))
        db.session.commit()

        _make_config(app, provider="delta_exchange", market="crypto")

        runtime_health.reset()
        runtime_health.record_success("delta_exchange", latency_ms=150.0)

        snapshot = build_market_health_snapshot()

        provider = next(p for p in snapshot["providers"] if p["provider"] == "delta_exchange")
        # The stored verification is still reported as-is (transparency for
        # anyone looking at the raw admin record)...
        assert provider["state"] == "ERROR"
        # ...but the derived, user-facing status prefers the live signal.
        assert provider["live_state"] == "HEALTHY"
        assert snapshot["status"] == "ready"
        runtime_health.reset()


def test_no_runtime_data_keeps_the_stale_verification_as_the_status(app):
    with app.app_context():
        from app.models.asset import Asset
        from app.extensions import db
        from app.models.api_config import APIConfig

        APIConfig.query.filter_by(provider="delta_exchange").delete()
        db.session.add(Asset(symbol="BTCUSDT", name="Bitcoin", market="crypto", is_active=True))
        db.session.commit()

        _make_config(app, provider="delta_exchange", market="crypto")

        runtime_health.reset()
        snapshot = build_market_health_snapshot()

        provider = next(p for p in snapshot["providers"] if p["provider"] == "delta_exchange")
        assert provider["state"] == "ERROR"
        assert provider["live_state"] == "ERROR"
        assert snapshot["status"] == "unavailable"


def test_last_update_prefers_the_more_recent_live_timestamp(app):
    from datetime import datetime, timedelta

    with app.app_context():
        from app.models.asset import Asset
        from app.extensions import db
        from app.models.api_config import APIConfig

        APIConfig.query.filter_by(provider="delta_exchange").delete()
        db.session.add(Asset(symbol="BTCUSDT", name="Bitcoin", market="crypto", is_active=True))
        db.session.commit()

        old_verification = datetime.utcnow() - timedelta(days=14)
        _make_config(app, provider="delta_exchange", market="crypto",
                     status="error", connection_status="error", last_sync=old_verification)

        runtime_health.reset()
        runtime_health.record_success("delta_exchange")
        snapshot = build_market_health_snapshot()

        assert snapshot["last_update"] is not None
        assert snapshot["last_update"] > old_verification.isoformat()
        runtime_health.reset()
