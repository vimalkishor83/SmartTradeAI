import pytest


@pytest.fixture
def super_admin_headers(app, client):
    with app.app_context():
        from flask_jwt_extended import create_access_token
        from app.extensions import db
        from app.models.user import Role, User

        role = Role.query.filter_by(name="admin").first()
        admin = User(
            username="live-price-config-admin",
            email="live-price-config-admin@example.com",
            role_id=role.id,
            approval_status="approved",
            is_super_admin=True,
        )
        admin.set_password("TestPass123!")
        db.session.add(admin)
        db.session.commit()
        token = create_access_token(identity=str(admin.id))

    return {"Authorization": f"Bearer {token}"}


def test_live_price_refresh_interval_round_trip(super_admin_headers, client):
    response = client.put(
        "/api/v1/admin/platform-config",
        headers=super_admin_headers,
        json={"live_price_refresh_interval_seconds": 1},
    )
    assert response.status_code == 200
    assert response.get_json()["live_price_refresh_interval_seconds"] == 1

    response = client.put(
        "/api/v1/admin/platform-config",
        headers=super_admin_headers,
        json={"live_price_refresh_interval_seconds": 60},
    )
    assert response.status_code == 200
    assert response.get_json()["live_price_refresh_interval_seconds"] == 60


@pytest.mark.parametrize("value", [0, 61, "fast", None])
def test_live_price_refresh_interval_is_bounded(super_admin_headers, client, value):
    response = client.put(
        "/api/v1/admin/platform-config",
        headers=super_admin_headers,
        json={"live_price_refresh_interval_seconds": value},
    )
    assert response.status_code == 400
