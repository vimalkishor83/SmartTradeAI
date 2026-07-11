"""
Integration test: real Flask app + in-memory SQLite DB + real JWT auth,
hitting the actual HTTP routes rather than calling functions directly.
Uses the risk API since it has no external network dependency (no
broker/market-data calls), making it the cleanest route to prove the
test harness itself (app/client fixtures, DB setup, auth) works
end-to-end before other route tests build on it.
"""
import pytest


@pytest.fixture
def authed_client(app, client):
    """Creates a real user in the in-memory test DB and returns
    (client, auth_headers) for making authenticated requests.
    create_app() already seeds default roles/subscriptions
    (_seed_initial_data) — reuse the seeded "free" role rather than
    creating a duplicate (roles.name is unique)."""
    with app.app_context():
        from app.extensions import db
        from app.models.user import User, Role

        role = Role.query.filter_by(name="free").first()
        user = User(username="testuser", email="test@example.com", role_id=role.id,
                     approval_status="approved")
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()

        from flask_jwt_extended import create_access_token
        token = create_access_token(identity=str(user.id))

    return client, {"Authorization": f"Bearer {token}"}


class TestPositionSizeRoute:
    def test_valid_request_returns_position_size(self, authed_client):
        client, headers = authed_client
        resp = client.post("/api/v1/risk/position-size", headers=headers, json={
            "capital": 100000, "risk_pct": 1, "entry": 100, "stop_loss": 95,
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["units"] == 200.0
        assert body["risk_amount"] == 1000.0

    def test_missing_required_field_returns_400(self, authed_client):
        client, headers = authed_client
        resp = client.post("/api/v1/risk/position-size", headers=headers, json={
            "capital": 100000, "risk_pct": 1, "entry": 100,
            # stop_loss missing
        })
        assert resp.status_code == 400

    def test_unauthenticated_request_rejected(self, client):
        resp = client.post("/api/v1/risk/position-size", json={
            "capital": 100000, "risk_pct": 1, "entry": 100, "stop_loss": 95,
        })
        assert resp.status_code in (401, 422)  # flask-jwt-extended returns 401/422 depending on error type

    def test_with_atr_uses_volatility_adjusted_sizing(self, authed_client):
        client, headers = authed_client
        resp = client.post("/api/v1/risk/position-size", headers=headers, json={
            "capital": 100000, "risk_pct": 1, "entry": 100, "stop_loss": 95,
            "atr": 100.0, "atr_history": [1, 2, 3, 4, 5],
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["volatility_regime"] == "high"


class TestRiskRewardRoute:
    def test_valid_request_returns_ratio(self, authed_client):
        client, headers = authed_client
        resp = client.post("/api/v1/risk/risk-reward", headers=headers, json={
            "entry": 100, "stop_loss": 95, "target": 110,
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ratio"] == 2.0
        assert body["label"] == "Good"


class TestPortfolioRiskRoute:
    def test_no_portfolio_returns_empty_result(self, authed_client):
        client, headers = authed_client
        resp = client.get("/api/v1/risk/portfolio", headers=headers)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["holdings"] == 0
        assert body["correlation"]["symbols"] == []
