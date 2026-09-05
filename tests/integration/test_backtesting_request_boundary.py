"""Route-level tests for malformed backtesting requests."""
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
            username="backtestboundary",
            email="backtestboundary@example.com",
            role_id=role.id,
            subscription_id=subscription.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("route", [
    "/api/v1/backtesting/run",
    "/api/v1/backtesting/walk-forward",
])
def test_non_object_body_returns_400_before_expensive_work(client, premium_headers, route):
    response = client.post(route, json=[], headers=premium_headers)

    assert response.status_code == 400
    assert response.get_json()["error"] == "request body must be a JSON object"


@pytest.mark.parametrize("payload, message", [
    ({"symbol": "BTC", "timeframe": "10h"}, "timeframe must be one of"),
    ({"symbol": "BTC", "initial_capital": "NaN"}, "initial_capital must be finite"),
    ({"symbol": "BTC", "commission": 0.02}, "commission must be between"),
    ({"symbol": "BTC", "n_windows": 1}, "n_windows must be between"),
])
def test_invalid_config_returns_400_before_asset_lookup(client, premium_headers, payload, message):
    route = "/api/v1/backtesting/walk-forward" if "n_windows" in payload else "/api/v1/backtesting/run"
    response = client.post(route, json=payload, headers=premium_headers)

    assert response.status_code == 400
    assert message in response.get_json()["error"]


@pytest.mark.parametrize("query, message", [
    ("timeframe=10h", "timeframe must be one of"),
    ("days=0", "days must be between"),
    ("limit=1000", "limit must be between"),
    ("market=gold", "market must be one of"),
])
def test_live_engine_query_limits_return_400_before_market_data(client, premium_headers, query, message):
    response = client.get(f"/api/v1/signals/backtest?{query}", headers=premium_headers)

    assert response.status_code == 400
    assert message in response.get_json()["error"]
