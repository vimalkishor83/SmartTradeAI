"""Regression tests for the database-backed per-asset performance route."""
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def login_headers(app):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, Subscription, User
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="premium").first()
        subscription = Subscription.query.filter_by(name="premium").first()
        user = User(
            username="signalperformancebyasset",
            email="signalperformancebyasset@example.com",
            role_id=role.id,
            subscription_id=subscription.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}


def test_signal_performance_by_asset_preserves_aggregate_contract(
    app, client, login_headers,
):
    with app.app_context():
        from app.extensions import db
        from app.models.asset import Asset
        from app.models.signal import SignalHistory

        now = datetime.utcnow()
        crypto = Asset(symbol="PERFCRYPTO", name="Performance Crypto", market="crypto", is_active=True)
        forex = Asset(symbol="PERFFOREX", name="Performance Forex", market="forex", is_active=True)
        db.session.add_all([crypto, forex])
        db.session.flush()
        db.session.add_all([
            SignalHistory(
                asset_id=crypto.id, timeframe="1h", confidence_score=80,
                outcome="win", pnl_pct=2.0, closed_at=now - timedelta(days=1),
            ),
            SignalHistory(
                asset_id=crypto.id, timeframe="1h", confidence_score=80,
                outcome="loss", pnl_pct=-1.0, closed_at=now - timedelta(days=2),
            ),
            SignalHistory(
                asset_id=forex.id, timeframe="4h", confidence_score=None,
                outcome="win", pnl_pct=1.0, closed_at=now - timedelta(days=3),
            ),
        ])
        db.session.commit()

    response = client.get("/api/v1/signals/performance/by-asset", headers=login_headers)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["lookback_days"] == 90
    assert payload["overall"] == {
        "total": 3, "wins": 2, "losses": 1, "win_rate": 66.7,
        "avg_pnl_pct": 0.667, "profit_factor": 3.0,
    }
    assert [(row["asset"], row["timeframe"], row["total"]) for row in payload["by_asset_timeframe"]] == [
        ("PERFCRYPTO", "1h", 2),
        ("PERFFOREX", "4h", 1),
    ]
    calibration = {row["band"]: row for row in payload["calibration"]}
    assert calibration["Strong"]["signals"] == 2
    assert calibration["Strong"]["actual_win_rate"] == 50.0
    assert calibration["Weak"]["signals"] == 1
    assert calibration["Weak"]["actual_win_rate"] == 100.0

    filtered = client.get(
        "/api/v1/signals/performance/by-asset?market=crypto",
        headers=login_headers,
    )
    assert filtered.status_code == 200
    assert filtered.get_json()["overall"]["total"] == 2
    assert [row["asset"] for row in filtered.get_json()["by_asset_timeframe"]] == ["PERFCRYPTO"]
