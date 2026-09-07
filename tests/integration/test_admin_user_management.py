"""Integration coverage for the Admin Users create/edit contract."""

import pytest


@pytest.fixture
def super_admin_headers(app, client):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, User
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="admin").first()
        admin = User(
            username="users_superadmin",
            email="users_superadmin@example.com",
            role_id=role.id,
            approval_status="approved",
            is_super_admin=True,
        )
        admin.set_password("TestPass123!")
        db.session.add(admin)
        db.session.commit()
        token = create_access_token(identity=str(admin.id))

    return {"Authorization": f"Bearer {token}"}


def _ids(app):
    with app.app_context():
        from app.models.user import Role, Subscription

        return (
            Role.query.filter_by(name="free").first().id,
            Subscription.query.filter_by(name="free").first().id,
        )


def test_admin_can_create_and_edit_user(client, app, super_admin_headers):
    role_id, subscription_id = _ids(app)

    response = client.post(
        "/api/v1/admin/users",
        headers=super_admin_headers,
        json={
            "first_name": " Test ",
            "last_name": " Trader ",
            "username": "  test_user_flow  ",
            "email": "  test_user_flow@example.com  ",
            "password": "TestPass123!",
            "role_id": role_id,
            "subscription_id": subscription_id,
        },
    )
    assert response.status_code == 201
    created = response.get_json()
    assert created["username"] == "test_user_flow"
    assert created["email"] == "test_user_flow@example.com"
    assert created["first_name"] == "Test"
    assert created["approval_status"] == "approved"
    user_id = created["id"]

    response = client.put(
        f"/api/v1/admin/users/{user_id}",
        headers=super_admin_headers,
        json={
            "first_name": "Updated",
            "last_name": "Account",
            "username": " updated_user_flow ",
            "email": " updated_user_flow@example.com ",
        },
    )
    assert response.status_code == 200
    updated = response.get_json()
    assert updated["username"] == "updated_user_flow"
    assert updated["email"] == "updated_user_flow@example.com"
    assert updated["first_name"] == "Updated"


def test_admin_user_mutations_reject_invalid_payloads(client, app, super_admin_headers):
    role_id, subscription_id = _ids(app)

    response = client.post(
        "/api/v1/admin/users",
        headers=super_admin_headers,
        json={
            "username": "invalid_role_user",
            "email": "invalid_role_user@example.com",
            "password": "TestPass123!",
            "role_id": "not-a-number",
            "subscription_id": subscription_id,
        },
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "Invalid role"

    response = client.put(
        "/api/v1/admin/users/1",
        headers=super_admin_headers,
        data="not-json",
        content_type="text/plain",
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "A non-empty JSON object is required"

    response = client.post(
        "/api/v1/admin/users",
        headers=super_admin_headers,
        json={
            "username": "invalid_subscription_user",
            "email": "invalid_subscription_user@example.com",
            "password": "TestPass123!",
            "role_id": role_id,
            "subscription_id": "not-a-number",
        },
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "Invalid subscription"


def test_regular_admin_cannot_create_user(client, app):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, User
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="admin").first()
        admin = User(
            username="users_regular_admin",
            email="users_regular_admin@example.com",
            role_id=role.id,
            approval_status="approved",
            is_super_admin=False,
        )
        admin.set_password("TestPass123!")
        db.session.add(admin)
        db.session.commit()
        token = create_access_token(identity=str(admin.id))

    response = client.post(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "username": "blocked_user",
            "email": "blocked_user@example.com",
            "password": "TestPass123!",
        },
    )
    assert response.status_code == 403
