"""Regression tests for streamed signal CSV exports."""
import csv
from datetime import datetime
from io import StringIO

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
            username="signalexports",
            email="signalexports@example.com",
            role_id=role.id,
            subscription_id=subscription.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}


def test_signal_csv_exports_keep_columns_and_joined_asset_values(
    app, client, login_headers,
):
    with app.app_context():
        from app.extensions import db
        from app.models.asset import Asset
        from app.models.signal import Signal, SignalHistory

        asset = Asset(symbol="CSVASSET", name="CSV Asset", market="crypto", is_active=True)
        db.session.add(asset)
        db.session.flush()
        signal = Signal(
            asset_id=asset.id, timeframe="1h", signal_type="BUY", status="active",
            entry_price=100, stop_loss=95, target1=110, risk_reward=2.0,
            confidence_score=82, reasoning="test signal",
            generated_at=datetime.utcnow(),
        )
        db.session.add(signal)
        db.session.flush()
        db.session.add(SignalHistory(
            signal_id=signal.id, asset_id=asset.id, timeframe="1h",
            signal_type="BUY", entry_price=100, stop_loss=95, target1=110,
            outcome="win", pnl_pct=10, duration_minutes=30,
            closed_at=datetime.utcnow(),
        ))
        db.session.commit()

    live_response = client.get("/api/v1/signals/export/csv", headers=login_headers)
    assert live_response.status_code == 200
    assert live_response.headers["Content-Type"].startswith("text/csv")
    assert "signals_" in live_response.headers["Content-Disposition"]
    live_csv = live_response.get_data(as_text=True)
    live_rows = list(csv.reader(StringIO(live_csv)))
    assert live_rows[0][:7] == [
        "Date", "Asset", "Market", "Timeframe", "Signal", "Entry", "Stop Loss",
    ]
    assert live_rows[1][1:9] == ["CSVASSET", "crypto", "1h", "BUY", "100.0", "95.0", "110.0", ""]

    history_response = client.get(
        "/api/v1/signals/history/export/csv", headers=login_headers,
    )
    assert history_response.status_code == 200
    assert history_response.headers["Content-Type"].startswith("text/csv")
    assert "signal_history_" in history_response.headers["Content-Disposition"]
    history_csv = history_response.get_data(as_text=True)
    history_rows = list(csv.reader(StringIO(history_csv)))
    assert history_rows[0][:7] == [
        "Date", "Asset", "Market", "Timeframe", "Signal", "Entry", "Outcome",
    ]
    assert history_rows[1][1:] == [
        "CSVASSET", "crypto", "1h", "BUY", "100.0", "win", "10.0", "30", "2.0",
    ]
