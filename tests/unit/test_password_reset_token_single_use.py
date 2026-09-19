"""Regression coverage for two related password-reset bugs:
1. The reset token was stateless and reusable — the same link could reset
   the password more than once within its 1-hour window. Fixed by binding
   a fingerprint of the password hash current at issue-time into the
   token; a token stops verifying the instant the password actually
   changes (see app/services/tokens.py).
2. Existing sessions survived a password reset — a stolen access token
   from before the reset kept working for the rest of its natural
   lifetime. Fixed by revoking all of the user's active UserSession rows
   as part of the reset (see app/auth/routes.py::reset_password).
"""
from app.models.user import Role, User
from app.models.user_session import UserSession
from app.services.tokens import make_reset_token


def _make_user(app):
    from app.extensions import db

    role = Role.query.filter_by(name="free").first()
    user = User(
        username="reset-token-user", email="reset-token-user@example.com",
        role_id=role.id, approval_status="approved", is_active=True,
    )
    user.set_password("OldPass123!")
    db.session.add(user)
    db.session.commit()
    return user


def test_reset_token_cannot_be_reused_after_a_successful_reset(app, client):
    with app.app_context():
        user = _make_user(app)
        token = make_reset_token(user.id, user.password_hash)

    first = client.post("/api/v1/auth/reset-password", json={"token": token, "password": "NewPass123!"})
    assert first.status_code == 200

    second = client.post("/api/v1/auth/reset-password", json={"token": token, "password": "AnotherPass456!"})
    assert second.status_code == 400
    assert "Invalid or expired" in second.get_json()["error"]


def test_reset_token_signed_before_a_manual_password_change_is_rejected(app, client):
    with app.app_context():
        from app.extensions import db
        user = _make_user(app)
        token = make_reset_token(user.id, user.password_hash)
        # Password changed through some other path (e.g. the user already
        # knew it and changed it directly) after the link was emailed.
        user.set_password("ChangedElsewhere789!")
        db.session.commit()

    response = client.post("/api/v1/auth/reset-password", json={"token": token, "password": "NewPass123!"})
    assert response.status_code == 400


def test_reset_password_revokes_existing_sessions(app, client):
    with app.app_context():
        from app.extensions import db
        from datetime import datetime, timedelta

        user = _make_user(app)
        session_row = UserSession(
            user_id=user.id, ip_address="127.0.0.1", user_agent="test",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        db.session.add(session_row)
        db.session.commit()
        session_id = session_row.id
        token = make_reset_token(user.id, user.password_hash)

    response = client.post("/api/v1/auth/reset-password", json={"token": token, "password": "NewPass123!"})
    assert response.status_code == 200

    with app.app_context():
        refreshed = UserSession.query.get(session_id)
        assert refreshed.revoked_at is not None
        assert refreshed.revoked_reason == "password_reset"
