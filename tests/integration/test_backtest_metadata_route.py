"""Regression coverage for persisted backtest provenance."""

from datetime import datetime

import pandas as pd
import pytest


@pytest.fixture
def premium_headers(app):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, Subscription, User
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="premium").first()
        subscription = Subscription.query.filter_by(name="premium").first()
        user = User(
            username="backtestrepro",
            email="backtestrepro@example.com",
            role_id=role.id,
            subscription_id=subscription.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}


def test_backtest_persists_reproducibility_metadata(
    app, client, premium_headers, monkeypatch,
):
    from app.extensions import db
    from app.models.asset import Asset
    from app.models.backtest import Backtest

    frame = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0},
        index=pd.date_range("2026-01-01", periods=120, freq="h"),
    )
    with app.app_context():
        asset = Asset(symbol="BTREPRO", name="Backtest Repro", market="crypto", is_active=True)
        db.session.add(asset)
        db.session.commit()

    monkeypatch.setattr(
        "app.api.v1.backtesting.market_fetcher.fetch",
        lambda *args, **kwargs: frame,
    )
    response = client.post(
        "/api/v1/backtesting/run",
        json={
            "symbol": "BTREPRO",
            "timeframe": "1h",
            "strategy": "rsi",
            "initial_capital": 10_000,
        },
        headers=premium_headers,
    )

    assert response.status_code == 200
    payload = response.get_json()
    provenance = payload["reproducibility"]
    assert provenance["backtest_id"] == payload["id"]
    assert provenance["engine_version"] == "strategy-backtest-v2"
    assert provenance["model_version"] == "not_applicable"
    assert len(provenance["config_fingerprint"]) == 64
    assert len(provenance["data_fingerprint"]) == 64
    assert provenance["data_candles"] == 120
    assert provenance["data_start"] == datetime(2026, 1, 1).isoformat()
    assert provenance["data_end"] == datetime(2026, 1, 5, 23).isoformat()

    with app.app_context():
        saved = db.session.get(Backtest, payload["id"])
        assert saved.engine_version == "strategy-backtest-v2"
        assert saved.model_version == "not_applicable"
        assert saved.config_fingerprint == provenance["config_fingerprint"]
        assert saved.data_fingerprint == provenance["data_fingerprint"]
        assert saved.data_candles == 120
