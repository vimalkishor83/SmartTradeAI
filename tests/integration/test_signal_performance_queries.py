"""Regression tests for the signal performance aggregation contract."""
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
            username="signalperformance",
            email="signalperformance@example.com",
            role_id=role.id,
            subscription_id=subscription.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}


def test_signal_performance_preserves_calibration_and_hourly_contract(
    app, client, login_headers,
):
    with app.app_context():
        from app.extensions import cache, db
        from app.models.asset import Asset
        from app.models.signal import SignalHistory

        cache.delete("signals_performance")
        now = datetime.utcnow().replace(second=0, microsecond=0)
        asset = Asset(symbol="SIGPERF", name="Signal Performance", market="crypto", is_active=True)
        db.session.add(asset)
        db.session.flush()
        db.session.add_all([
            SignalHistory(
                asset_id=asset.id, timeframe="1h", signal_type="BUY",
                confidence_score=85, outcome="win", pnl_pct=2.0,
                duration_minutes=30, closed_at=now - timedelta(hours=1),
            ),
            SignalHistory(
                asset_id=asset.id, timeframe="1h", signal_type="SELL",
                confidence_score=85, outcome="loss", pnl_pct=-1.0,
                duration_minutes=45, closed_at=now - timedelta(hours=2),
            ),
            SignalHistory(
                asset_id=asset.id, timeframe="4h", signal_type="BUY",
                confidence_score=None, outcome="neutral", pnl_pct=0.2,
                duration_minutes=60, closed_at=now - timedelta(hours=3),
            ),
        ])
        db.session.commit()

    response = client.get("/api/v1/signals/performance", headers=login_headers)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["overall"]["total_closed"] == 3
    assert payload["overall"]["win_rate"] == 33.3
    assert payload["overall"]["total_pnl_pct"] == 1.2
    assert payload["by_market"] == [{
        "market": "crypto", "trades": 3, "win_rate": 33.3, "avg_pnl": 0.4,
    }]
    assert payload["hourly_win_rate"]
    assert len(payload["calibration"]) == 4
    calibration = {row["band"]: row for row in payload["calibration"]}
    assert calibration["Weak"]["signals"] == 1
    assert calibration["Weak"]["actual_win_rate"] is None
    assert calibration["Strong"]["signals"] == 2
    assert calibration["Strong"]["actual_win_rate"] == 50.0
