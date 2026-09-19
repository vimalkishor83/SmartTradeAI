"""Regression coverage for a real auth-bypass: /auth/login issues a
short-lived "partial_token" the moment a password check succeeds but
before 2FA is verified (additional_claims={"totp_pending": True}). That
token used to be a fully valid, correctly-signed JWT accepted by every
@login_required-guarded endpoint (~70 routes) for its whole 5-minute
lifetime, on password alone — defeating the purpose of 2FA. Every
decorator that independently calls verify_jwt_in_request() must reject
a token carrying totp_pending=True. See app/auth/decorators.py.
"""
from flask_jwt_extended import create_access_token

from app.models.user import Role, User


def _make_totp_pending_client(app, client):
    with app.app_context():
        from app.extensions import db

        role = Role.query.filter_by(name="free").first()
        user = User(
            username="totp-pending-user", email="totp-pending-user@example.com",
            role_id=role.id, approval_status="approved", is_active=True,
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()

        token = create_access_token(
            identity=str(user.id), additional_claims={"totp_pending": True},
        )
    return {"Authorization": f"Bearer {token}"}


def test_totp_pending_token_rejected_by_login_required(app, client):
    headers = _make_totp_pending_client(app, client)
    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 401
    assert "2FA" in response.get_json()["error"]


def test_totp_pending_token_rejected_by_roles_required(app, client):
    headers = _make_totp_pending_client(app, client)
    response = client.get("/api/v1/admin/dashboard", headers=headers)
    assert response.status_code == 401
    assert "2FA" in response.get_json()["error"]


def test_normal_token_without_totp_pending_still_works(app, client):
    with app.app_context():
        from app.extensions import db

        role = Role.query.filter_by(name="free").first()
        user = User(
            username="normal-user", email="normal-user@example.com",
            role_id=role.id, approval_status="approved", is_active=True,
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
