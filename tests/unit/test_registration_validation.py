"""Regression coverage for public registration input validation."""

import pytest

from app.models.user import User


@pytest.fixture(autouse=True)
def disable_rate_limit_for_validation_tests(app):
    """Keep shared Redis rate-limit state from masking validation responses."""
    app.config["RATELIMIT_ENABLED"] = False


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
    response = client.post("/api/v1/auth/register", json=_payload(
        username="  new_trader  ", email="TRADER@EXAMPLE.COM"
    ))

    assert response.status_code == 201
    with app.app_context():
        user = User.query.filter_by(username="new_trader").one()
        assert user.email == "trader@example.com"


def test_registration_rejects_invalid_username(app, client):
    with app.app_context():
        before = User.query.count()

    response = client.post("/api/v1/auth/register", json=_payload(username="bad name"))

    assert response.status_code == 400
    assert "Username" in response.get_json()["error"]
    with app.app_context():
        assert User.query.count() == before


def test_registration_rejects_short_password_and_malformed_email(client):
    short_password = client.post("/api/v1/auth/register", json=_payload(password="short"))
    malformed_email = client.post("/api/v1/auth/register", json=_payload(email="not-an-email"))

    assert short_password.status_code == 400
    assert malformed_email.status_code == 400


def test_registration_rejects_missing_required_fields(client):
    response = client.post("/api/v1/auth/register", json={"accept_terms": True})

    assert response.status_code == 400
    assert "required" in response.get_json()["error"]
