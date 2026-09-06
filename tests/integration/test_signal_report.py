"""Integration coverage for the bounded Reporting Center aggregates."""

from datetime import datetime

import pytest


@pytest.fixture
def report_headers(app):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, User
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="free").first()
        user = User(
            username="reportuser",
            email="reportuser@example.com",
            role_id=role.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}


def test_report_aggregates_are_range_bounded_and_explicit(app, client, report_headers):
    with app.app_context():
        from app.extensions import cache, db
        from app.models.asset import Asset
        from app.models.signal import SignalHistory

        cache.clear()
        crypto = Asset(symbol="REPORTBTC", name="Report Crypto", market="crypto", is_active=True)
        forex = Asset(symbol="REPORTFX", name="Report Forex", market="forex", is_active=True)
        db.session.add_all([crypto, forex])
        db.session.flush()
        db.session.add_all([
            SignalHistory(
                asset_id=crypto.id, timeframe="1h", signal_type="BUY",
                confidence_score=80, outcome="win", pnl_pct=2.0,
                duration_minutes=30, closed_at=datetime(2026, 9, 2, 10),
            ),
            SignalHistory(
                asset_id=crypto.id, timeframe="1h", signal_type="SELL",
                confidence_score=70, outcome="loss", pnl_pct=-1.0,
                duration_minutes=60, closed_at=datetime(2026, 9, 3, 10),
            ),
            SignalHistory(
                asset_id=forex.id, timeframe="4h", signal_type="BUY",
                confidence_score=None, outcome="neutral", pnl_pct=0.5,
                duration_minutes=90, closed_at=datetime(2026, 9, 4, 10),
            ),
            SignalHistory(
                asset_id=forex.id, timeframe="4h", signal_type="BUY",
                confidence_score=90, outcome="win", pnl_pct=9.0,
                duration_minutes=90, closed_at=datetime(2026, 8, 31, 10),
            ),
        ])
        db.session.commit()

    response = client.get(
        "/api/v1/signals/report?from=2026-09-01&to=2026-09-06",
        headers=report_headers,
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["range"] == {
        "from": "2026-09-01", "to": "2026-09-06", "timezone": "UTC", "days": 6,
    }
    assert payload["overall"] == {
        "total": 3, "wins": 1, "losses": 1, "neutral": 1,
        "win_rate": 50.0, "net_pnl_pct": 1.5, "avg_pnl_pct": 0.5,
        "profit_factor": 2.0, "avg_duration_minutes": 60.0,
    }
    assert {row["name"] for row in payload["by_market"]} == {"crypto", "forex"}
    assert {row["name"] for row in payload["by_timeframe"]} == {"1h", "4h"}
    assert [row["date"] for row in payload["daily"]] == ["2026-09-02", "2026-09-03", "2026-09-04"]


@pytest.mark.parametrize("query", [
    "from=not-a-date&to=2026-09-06",
    "from=2026-09-07&to=2026-09-06",
    "from=2024-01-01&to=2026-09-06",
])
def test_report_rejects_invalid_or_oversized_ranges(client, report_headers, query):
    response = client.get("/api/v1/signals/report?" + query, headers=report_headers)

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_history_export_accepts_the_same_date_range(app, client, report_headers):
    with app.app_context():
        from app.extensions import db
        from app.models.asset import Asset
        from app.models.signal import SignalHistory

        asset = Asset(symbol="EXPORTREPORT", name="Export Report", market="crypto", is_active=True)
        db.session.add(asset)
        db.session.flush()
        db.session.add_all([
            SignalHistory(
                asset_id=asset.id, timeframe="1h", signal_type="BUY",
                outcome="win", pnl_pct=1.0, closed_at=datetime(2026, 9, 5, 10),
            ),
            SignalHistory(
                asset_id=asset.id, timeframe="1h", signal_type="SELL",
                outcome="loss", pnl_pct=-1.0, closed_at=datetime(2026, 8, 20, 10),
            ),
        ])
        db.session.commit()

    response = client.get(
        "/api/v1/signals/history/export/csv?from=2026-09-01&to=2026-09-06",
        headers=report_headers,
    )

    assert response.status_code == 200
    assert "2026-09-01_2026-09-06" in response.headers["Content-Disposition"]
    body = response.get_data(as_text=True)
    assert "EXPORTREPORT" in body
    assert "2026-08-20" not in body
