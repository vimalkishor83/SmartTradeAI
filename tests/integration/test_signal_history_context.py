"""Regression tests for active-signal historical context."""
from datetime import datetime

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
            username="signalhistorycontext",
            email="signalhistorycontext@example.com",
            role_id=role.id,
            subscription_id=subscription.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}


def test_active_signal_includes_grouped_historical_context(app, client, login_headers):
    with app.app_context():
        from app.extensions import db
        from app.models.asset import Asset
        from app.models.signal import Signal, SignalHistory

        asset = Asset(symbol="HISTORYCTX", name="History Context", market="crypto", is_active=True)
        db.session.add(asset)
        db.session.flush()
        signal = Signal(
            asset_id=asset.id,
            timeframe="1h",
            signal_type="BUY",
            entry_price=100,
            stop_loss=98,
            target1=103,
            confidence_score=78,
            status="active",
            generated_at=datetime.utcnow(),
        )
        db.session.add(signal)
        db.session.flush()
        db.session.add_all([
            SignalHistory(
                asset_id=asset.id, timeframe="1h", signal_type="BUY",
                outcome="win", pnl_pct=2.0,
            ),
            SignalHistory(
                asset_id=asset.id, timeframe="1h", signal_type="SELL",
                outcome="loss", pnl_pct=-1.0,
            ),
            SignalHistory(
                asset_id=asset.id, timeframe="1h", signal_type="BUY",
                outcome="neutral", pnl_pct=0.0,
            ),
        ])
        db.session.commit()
        signal_id = signal.id

    response = client.get("/api/v1/signals/?per_page=100", headers=login_headers)

    assert response.status_code == 200
    row = next(item for item in response.get_json()["signals"] if item["id"] == signal_id)
    assert row["historical_context"] == {
        "sample_size": 3,
        "decisive_sample_size": 2,
        "wins": 1,
        "losses": 1,
        "neutral": 1,
        "accuracy": 50.0,
        "avg_pnl_pct": 0.33,
    }

    detail = client.get(f"/api/v1/signals/{signal_id}", headers=login_headers)
    assert detail.status_code == 200
    assert detail.get_json()["historical_context"] == row["historical_context"]


def test_active_signal_without_history_has_explicit_empty_context(app, client, login_headers):
    with app.app_context():
        from app.extensions import db
        from app.models.asset import Asset
        from app.models.signal import Signal

        asset = Asset(symbol="NOHISTORYCTX", name="No History Context", market="crypto", is_active=True)
        db.session.add(asset)
        db.session.flush()
        signal = Signal(
            asset_id=asset.id,
            timeframe="4h",
            signal_type="SELL",
            entry_price=100,
            stop_loss=102,
            target1=96,
            confidence_score=72,
            status="active",
            generated_at=datetime.utcnow(),
        )
        db.session.add(signal)
        db.session.commit()
        signal_id = signal.id

    response = client.get(f"/api/v1/signals/{signal_id}", headers=login_headers)

    assert response.status_code == 200
    assert response.get_json()["historical_context"] == {
        "sample_size": 0,
        "decisive_sample_size": 0,
        "wins": 0,
        "losses": 0,
        "neutral": 0,
        "accuracy": None,
        "avg_pnl_pct": None,
    }
