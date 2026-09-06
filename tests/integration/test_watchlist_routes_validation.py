"""Authenticated HTTP coverage for Watchlist request-shape validation."""

import pytest


@pytest.fixture
def watchlist_client(app, client):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, User
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="free").first()
        user = User(
            username="watchlist-test",
            email="watchlist-test@example.com",
            role_id=role.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))

    return client, {"Authorization": f"Bearer {token}"}


def test_create_watchlist_requires_object_body(watchlist_client):
    client, headers = watchlist_client

    response = client.post("/api/v1/watchlist/", headers=headers, json=[])

    assert response.status_code == 400
    assert response.get_json()["error"] == "request body must be a JSON object"


def test_create_watchlist_rejects_non_string_name(watchlist_client):
    client, headers = watchlist_client

    response = client.post(
        "/api/v1/watchlist/", headers=headers, json={"name": {"invalid": True}}
    )

    assert response.status_code == 400
    assert "name must be a string" in response.get_json()["error"]


def test_add_watchlist_item_validates_body_before_asset_lookup(watchlist_client):
    client, headers = watchlist_client
    created = client.post("/api/v1/watchlist/", headers=headers, json={"name": "Test"})
    watchlist_id = created.get_json()["id"]

    response = client.post(
        f"/api/v1/watchlist/{watchlist_id}/items",
        headers=headers,
        json={"symbol": ["BTCUSD"]},
    )

    assert response.status_code == 400
    assert "symbol must be a string" in response.get_json()["error"]


def test_add_watchlist_item_rejects_string_boolean_flags(watchlist_client):
    client, headers = watchlist_client
    created = client.post("/api/v1/watchlist/", headers=headers, json={"name": "Test"})
    watchlist_id = created.get_json()["id"]

    response = client.post(
        f"/api/v1/watchlist/{watchlist_id}/items",
        headers=headers,
        json={"symbol": "BTCUSD", "alert_repeat": "false"},
    )

    assert response.status_code == 400
    assert "alert_repeat must be a boolean" in response.get_json()["error"]
