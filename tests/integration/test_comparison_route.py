"""
Multi-asset comparison route (feature 10 of this session's build) —
validation paths only (the happy path needs real market data, already
verified manually against the live app; these tests cover the pure
input-validation logic that doesn't need real OHLCV)."""
import pytest


@pytest.fixture
def authed_client(app, client):
    with app.app_context():
        from app.extensions import db
        from app.models.user import User, Role

        role = Role.query.filter_by(name="free").first()
        user = User(username="cmpuser", email="cmp@example.com", role_id=role.id,
                     approval_status="approved")
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()

        from flask_jwt_extended import create_access_token
        token = create_access_token(identity=str(user.id))

    return client, {"Authorization": f"Bearer {token}"}


class TestCompareValidation:
    def test_single_symbol_rejected(self, authed_client):
        client, headers = authed_client
        resp = client.get("/api/v1/comparison/?symbols=BTCUSDT", headers=headers)
        assert resp.status_code == 400

    def test_too_many_symbols_rejected(self, authed_client):
        client, headers = authed_client
        resp = client.get("/api/v1/comparison/?symbols=A,B,C,D,E,F", headers=headers)
        assert resp.status_code == 400
        assert "Maximum 5" in resp.get_json()["error"]

    def test_unknown_symbol_returns_404(self, authed_client):
        client, headers = authed_client
        resp = client.get("/api/v1/comparison/?symbols=AAAAAA,BBBBBB", headers=headers)
        assert resp.status_code == 404

    def test_no_symbols_param_rejected(self, authed_client):
        client, headers = authed_client
        resp = client.get("/api/v1/comparison/", headers=headers)
        assert resp.status_code == 400

    def test_unauthenticated_rejected(self, client):
        resp = client.get("/api/v1/comparison/?symbols=A,B")
        assert resp.status_code in (401, 422)
