import pytest


@pytest.fixture
def dashboard_preferences_client(app, client):
    with app.app_context():
        from flask_jwt_extended import create_access_token
        from app.extensions import db
        from app.models.user import Role, User

        role = Role.query.filter_by(name="free").first()
        user = User(
            username="dashboard-preferences-user",
            email="dashboard-preferences@example.com",
            role_id=role.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))

    return client, {"Authorization": f"Bearer {token}"}


def test_dashboard_preferences_default_and_round_trip(dashboard_preferences_client):
    client, headers = dashboard_preferences_client

    response = client.get("/api/v1/auth/me/dashboard-preferences", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["preferences"]["timeframe"] == "1h"

    response = client.put(
        "/api/v1/auth/me/dashboard-preferences",
        headers=headers,
        json={"timeframe": "all"},
    )
    assert response.status_code == 200
    assert response.get_json()["preferences"] == {"timeframe": "all"}

    response = client.get("/api/v1/auth/me/dashboard-preferences", headers=headers)
    assert response.get_json()["preferences"] == {"timeframe": "all"}


@pytest.mark.parametrize("timeframe", ["3h", "", 1, None])
def test_dashboard_preferences_reject_unsupported_values(dashboard_preferences_client, timeframe):
    client, headers = dashboard_preferences_client
    response = client.put(
        "/api/v1/auth/me/dashboard-preferences",
        headers=headers,
        json={"timeframe": timeframe},
    )
    assert response.status_code == 400
