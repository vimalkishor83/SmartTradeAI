import pytest


@pytest.fixture
def broker_headers(app):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, Subscription, User
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="premium").first()
        subscription = Subscription.query.filter_by(name="premium").first()
        user = User(
            username="brokerconnection",
            email="brokerconnection@example.com",
            role_id=role.id,
            subscription_id=subscription.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))

    return {"Authorization": f"Bearer {token}"}


class TestBrokerConnectionValidation:
    def test_connect_requires_object_body_and_supported_provider(self, client, broker_headers):
        response = client.post(
            "/api/v1/trading/broker/connect",
            headers=broker_headers,
            json=[],
        )
        assert response.status_code == 400
        assert response.get_json()["error"] == "request body must be a JSON object"

        response = client.post(
            "/api/v1/trading/broker/connect",
            headers=broker_headers,
            json={"provider": "not-a-broker", "api_key": "key"},
        )
        assert response.status_code == 400
        assert "Unknown broker" in response.get_json()["error"]

    @pytest.mark.parametrize("api_key", ["", "x" * 1025, "valid\nkey"])
    def test_connect_rejects_invalid_api_key(self, client, broker_headers, api_key):
        response = client.post(
            "/api/v1/trading/broker/connect",
            headers=broker_headers,
            json={"provider": "oanda", "api_key": api_key},
        )
        assert response.status_code == 400

    def test_api_key_only_provider_does_not_require_secret(self, app, client, broker_headers):
        response = client.post(
            "/api/v1/trading/broker/connect",
            headers=broker_headers,
            json={"provider": " OANDA ", "api_key": "oanda-token-123"},
        )

        assert response.status_code == 200
        payload = response.get_json()
        assert payload["provider"] == "oanda"
        assert payload["has_key"] is True
        assert payload["has_secret"] is False

        with app.app_context():
            from app.models.api_config import UserBrokerCredential

            credential = UserBrokerCredential.query.filter_by(provider="oanda").one()
            assert credential.api_key_encrypted != "oanda-token-123"
            assert credential.get_api_key() == "oanda-token-123"
            assert credential.get_api_secret() is None

    def test_secret_based_provider_requires_secret(self, client, broker_headers):
        response = client.post(
            "/api/v1/trading/broker/connect",
            headers=broker_headers,
            json={"provider": "binance", "api_key": "key-only"},
        )

        assert response.status_code == 400
        assert "api_secret" in response.get_json()["error"]

