"""Regression coverage for public registration input validation."""

from uuid import uuid4

from app.models.user import User


def _post(client, payload):
    """Use an isolated test IP so Redis-backed limits cannot mask validation."""
    token = uuid4().int
    client_ip = f"198.51.{(token >> 8) % 254 + 1}.{token % 254 + 1}"
    return client.post(
        "/api/v1/auth/register",
        json=payload,
        environ_base={"REMOTE_ADDR": client_ip},
    )


def _payload(**overrides):
    payload = {
        "username": "new_trader",
        "email": "trader@example.com",
        "password": "StrongPass123!",
        "accept_terms": True,
    }
    payload.update(overrides)
    return payload


def test_registration_normalizes_email_and_username(app, client):
    response = _post(client, _payload(username="  new_trader  ", email="TRADER@EXAMPLE.COM"))

    assert response.status_code == 201
    with app.app_context():
        user = User.query.filter_by(username="new_trader").one()
        assert user.email == "trader@example.com"


def test_registration_rejects_invalid_username(app, client):
    with app.app_context():
        before = User.query.count()

    response = _post(client, _payload(username="bad name"))

    assert response.status_code == 400
    assert "Username" in response.get_json()["error"]
    with app.app_context():
        assert User.query.count() == before


def test_registration_rejects_short_password_and_malformed_email(client):
    short_password = _post(client, _payload(password="short"))
    malformed_email = _post(client, _payload(email="not-an-email"))

    assert short_password.status_code == 400
    assert malformed_email.status_code == 400


def test_registration_rejects_missing_required_fields(client):
    response = _post(client, {"accept_terms": True})

    assert response.status_code == 400
    assert "required" in response.get_json()["error"]
