"""Integration coverage for the authenticated profile mutation boundary."""

import pytest


@pytest.fixture
def profile_client(app, client):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, User
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="free").first()
        user = User(username="profiletest", email="profile@example.com", role_id=role.id,
                    approval_status="approved")
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))

    return client, {"Authorization": f"Bearer {token}"}


class TestProfileUpdate:
    def test_account_delete_rejects_non_object_body(self, profile_client):
        client, headers = profile_client
        response = client.delete("/api/v1/auth/me", headers=headers, json=[])

        assert response.status_code == 400
        assert response.get_json()["error"] == "request body must be a JSON object"

    def test_non_object_body_returns_400(self, profile_client):
        client, headers = profile_client
        response = client.put("/api/v1/auth/me", headers=headers, json=[])

        assert response.status_code == 400
        assert response.get_json()["error"] == "request body must be a JSON object"

    def test_valid_profile_and_risk_settings_are_persisted(self, profile_client):
        client, headers = profile_client
        response = client.put("/api/v1/auth/me", headers=headers, json={
            "first_name": "Vimal",
            "last_name": "Trader",
            "phone": "+919876543210",
            "theme": "light",
            "email_notifications": False,
            "telegram_enabled": True,
            "telegram_chat_id": "123456",
            "account_size": 250000,
            "risk_per_trade_pct": 1.5,
            "min_confidence_filter": 75,
        })

        assert response.status_code == 200
        body = response.get_json()["user"]
        assert body["first_name"] == "Vimal"
        assert body["theme"] == "light"
        assert body["account_size"] == 250000
        assert body["risk_per_trade_pct"] == 1.5
        assert body["min_confidence_filter"] == 75

    @pytest.mark.parametrize("payload", [
        {"email_notifications": "false"},
        {"account_size": "nan"},
        {"risk_per_trade_pct": 21},
        {"min_confidence_filter": 101},
        {"theme": ["dark"]},
        {"first_name": "x" * 81},
    ])
    def test_invalid_profile_values_return_400(self, profile_client, payload):
        client, headers = profile_client
        response = client.put("/api/v1/auth/me", headers=headers, json=payload)

        assert response.status_code == 400

    def test_password_change_requires_strength_and_current_password(self, profile_client):
        client, headers = profile_client
        response = client.put("/api/v1/auth/me", headers=headers, json={
            "current_password": "TestPass123!",
            "password": "short",
        })

        assert response.status_code == 400
        assert "between 8 and 256" in response.get_json()["error"]
