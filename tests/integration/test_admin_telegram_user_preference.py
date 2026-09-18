import pytest


@pytest.fixture
def super_admin_client(app, client):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, User
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="admin").first()
        admin = User(
            username="tgpref-superadmin", email="tgpref-superadmin@example.com",
            role_id=role.id, approval_status="approved", is_super_admin=True,
        )
        admin.set_password("TestPass123!")
        db.session.add(admin)

        free_role = Role.query.filter_by(name="free").first()
        target = User(
            username="tgpref-target", email="tgpref-target@example.com",
            role_id=free_role.id, approval_status="approved",
        )
        target.set_password("TestPass123!")
        db.session.add(target)
        db.session.commit()

        token = create_access_token(identity=str(admin.id))
        target_id = target.id

    return client, {"Authorization": f"Bearer {token}"}, target_id


@pytest.fixture
def regular_admin_client(app, client):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, User
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="admin").first()
        admin = User(
            username="tgpref-regadmin", email="tgpref-regadmin@example.com",
            role_id=role.id, approval_status="approved", is_super_admin=False,
        )
        admin.set_password("TestPass123!")
        db.session.add(admin)
        db.session.commit()
        token = create_access_token(identity=str(admin.id))

    return client, {"Authorization": f"Bearer {token}"}


def test_get_preference_defaults_to_null_categories(super_admin_client):
    client, headers, target_id = super_admin_client

    response = client.get(f"/api/v1/admin/users/{target_id}/telegram-preference", headers=headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["preference"]["categories"] is None
    assert "signal" in body["available_categories"]


def test_super_admin_can_set_categories(super_admin_client):
    client, headers, target_id = super_admin_client

    response = client.put(
        f"/api/v1/admin/users/{target_id}/telegram-preference",
        headers=headers, json={"categories": ["signal", "watchlist"]},
    )
    assert response.status_code == 200
    assert response.get_json()["preference"]["categories"] == ["signal", "watchlist"]

    response = client.get(f"/api/v1/admin/users/{target_id}/telegram-preference", headers=headers)
    assert response.get_json()["preference"]["categories"] == ["signal", "watchlist"]


def test_rejects_unknown_category(super_admin_client):
    client, headers, target_id = super_admin_client

    response = client.put(
        f"/api/v1/admin/users/{target_id}/telegram-preference",
        headers=headers, json={"categories": ["not_a_real_category"]},
    )
    assert response.status_code == 400


def test_regular_admin_can_read_but_not_write(regular_admin_client, super_admin_client):
    client, headers = regular_admin_client
    _, _, target_id = super_admin_client

    assert client.get(f"/api/v1/admin/users/{target_id}/telegram-preference", headers=headers).status_code == 200
    response = client.put(
        f"/api/v1/admin/users/{target_id}/telegram-preference",
        headers=headers, json={"categories": ["signal"]},
    )
    assert response.status_code == 403


def test_null_categories_clears_restriction(super_admin_client):
    client, headers, target_id = super_admin_client

    client.put(
        f"/api/v1/admin/users/{target_id}/telegram-preference",
        headers=headers, json={"categories": ["signal"]},
    )
    response = client.put(
        f"/api/v1/admin/users/{target_id}/telegram-preference",
        headers=headers, json={"categories": None},
    )
    assert response.status_code == 200
    assert response.get_json()["preference"]["categories"] is None
