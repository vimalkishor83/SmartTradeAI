import pytest


@pytest.fixture
def ai_preferences_client(app, client):
    with app.app_context():
        from flask_jwt_extended import create_access_token
        from app.extensions import db
        from app.models.asset import Asset
        from app.models.user import Role, User

        role = Role.query.filter_by(name="free").first()
        user = User(
            username="ai-preferences-user",
            email="ai-preferences@example.com",
            role_id=role.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        asset = Asset(
            symbol="AIPREF",
            name="AI Preference Asset",
            market="crypto",
            is_active=True,
        )
        db.session.add_all([user, asset])
        db.session.commit()
        token = create_access_token(identity=str(user.id))
        asset_id = asset.id

    return client, {"Authorization": f"Bearer {token}"}, asset_id


def test_ai_insights_preferences_default_and_round_trip(ai_preferences_client):
    client, headers, asset_id = ai_preferences_client

    response = client.get("/api/v1/auth/me/ai-insights-preferences", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["preferences"] == {
        "asset_id": None,
        "timeframes": ["1h", "4h", "1d"],
    }

    response = client.put(
        "/api/v1/auth/me/ai-insights-preferences",
        headers=headers,
        json={"asset_id": asset_id, "timeframes": ["1d", "1h"]},
    )
    assert response.status_code == 200
    assert response.get_json()["preferences"] == {
        "asset_id": asset_id,
        "timeframes": ["1h", "1d"],
    }

    response = client.get("/api/v1/auth/me/ai-insights-preferences", headers=headers)
    assert response.get_json()["preferences"]["asset_id"] == asset_id
    assert response.get_json()["preferences"]["timeframes"] == ["1h", "1d"]


@pytest.mark.parametrize(
    "payload",
    [
        {"asset_id": 999999, "timeframes": ["1h"]},
        {"asset_id": None, "timeframes": []},
        {"asset_id": None, "timeframes": ["3h"]},
        {"asset_id": None, "timeframes": ["1h", "1h"]},
    ],
)
def test_ai_insights_preferences_reject_invalid_values(ai_preferences_client, payload):
    client, headers, _asset_id = ai_preferences_client

    response = client.put(
        "/api/v1/auth/me/ai-insights-preferences",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 400
