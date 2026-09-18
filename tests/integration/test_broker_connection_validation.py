import pytest


@pytest.fixture(autouse=True)
def _broker_connections_enabled(app):
    """These tests exercise POST /broker/connect's request-body/provider
    validation specifically -- they predate the BROKER_CONNECTIONS_ENABLED
    safety gate (app/services/safety.py::broker_connections_enabled(),
    checked first in the route and short-circuiting to 403 before any of
    this validation runs), which the development environment now sets to
    disabled by default. Enabling it just for this module's tests restores
    coverage of the validation logic without touching the gate itself or
    any other environment's configured value -- the gate's own on/off
    behavior isn't what's under test here.
    """
    previous = app.config.get("BROKER_CONNECTIONS_ENABLED")
    app.config["BROKER_CONNECTIONS_ENABLED"] = True
    yield
    app.config["BROKER_CONNECTIONS_ENABLED"] = previous


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

