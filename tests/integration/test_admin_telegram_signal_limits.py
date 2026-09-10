import pytest


@pytest.fixture
def super_admin_client(app, client):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, User
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="admin").first()
        user = User(
            username="telegram-limits-superadmin",
            email="telegram-limits-superadmin@example.com",
            role_id=role.id,
            approval_status="approved",
            is_super_admin=True,
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))

    return client, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def regular_admin_client(app, client):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, User
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="admin").first()
        user = User(
            username="telegram-limits-admin",
            email="telegram-limits-admin@example.com",
            role_id=role.id,
            approval_status="approved",
            is_super_admin=False,
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))

    return client, {"Authorization": f"Bearer {token}"}


def test_super_admin_can_read_and_update_signal_limits(super_admin_client):
    client, headers = super_admin_client

    response = client.get("/api/v1/admin/telegram-signal-limits", headers=headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["settings"]["enabled"] is True
    assert body["assets"]
    assert body["timeframes"]

    asset_id = body["assets"][0]["id"]
    timeframe = body["timeframes"][0]
    response = client.put(
        "/api/v1/admin/telegram-signal-limits",
        headers=headers,
        json={"enabled": True, "asset_ids": [asset_id], "timeframes": [timeframe]},
    )
    assert response.status_code == 200
    settings = response.get_json()["settings"]
    assert settings["asset_ids"] == [asset_id]
    assert settings["timeframes"] == [timeframe]


def test_regular_admin_can_read_but_cannot_change_signal_limits(regular_admin_client):
    client, headers = regular_admin_client

    assert client.get("/api/v1/admin/telegram-signal-limits", headers=headers).status_code == 200
    response = client.put(
        "/api/v1/admin/telegram-signal-limits",
        headers=headers,
        json={"enabled": False, "asset_ids": [], "timeframes": []},
    )
    assert response.status_code == 403


def test_signal_limits_reject_unknown_assets_and_timeframes(super_admin_client):
    client, headers = super_admin_client

    response = client.put(
        "/api/v1/admin/telegram-signal-limits",
        headers=headers,
        json={"asset_ids": [999999], "timeframes": ["15m"]},
    )
    assert response.status_code == 400

    response = client.put(
        "/api/v1/admin/telegram-signal-limits",
        headers=headers,
        json={"asset_ids": [], "timeframes": ["99x"]},
    )
    assert response.status_code == 400
