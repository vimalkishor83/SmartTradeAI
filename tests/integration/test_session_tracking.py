"""Integration test: real Flask app + in-memory SQLite DB, hitting the
actual /login, /refresh, /logout HTTP routes to prove session tracking
and server-side revocation actually work end-to-end — not just that the
model/blocklist-loader logic is individually correct. The critical case
is the last one: a token that is still cryptographically valid (not
expired) must be rejected the instant its UserSession is revoked, since
that's the entire point of adding this over flask-jwt-extended's default
stateless-JWT behavior.
"""
import pytest


@pytest.fixture
def registered_user(app):
    with app.app_context():
        from app.extensions import db
        from app.models.user import User, Role

        role = Role.query.filter_by(name="free").first()
        user = User(username="sessiontest", email="sessiontest@example.com", role_id=role.id,
                    approval_status="approved")
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        return user.id


class TestSessionTracking:
    def test_login_creates_session_row(self, app, client, registered_user):
        resp = client.post("/api/v1/auth/login", json={
            "email": "sessiontest", "password": "TestPass123!",
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["access_token"] and body["refresh_token"]

        with app.app_context():
            from app.models.user_session import UserSession
            sessions = UserSession.query.filter_by(user_id=registered_user).all()
            assert len(sessions) == 1
            assert sessions[0].is_active is True
            assert sessions[0].ip_address is not None

    def test_logout_revokes_session_and_blocks_further_requests(self, app, client, registered_user):
        resp = client.post("/api/v1/auth/login", json={
            "email": "sessiontest", "password": "TestPass123!",
        })
        access_token = resp.get_json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # Token works before logout
        resp = client.get("/api/v1/auth/me", headers=headers)
        assert resp.status_code == 200

        resp = client.post("/api/v1/auth/logout", headers=headers)
        assert resp.status_code == 200

        with app.app_context():
            from app.models.user_session import UserSession
            session_row = UserSession.query.filter_by(user_id=registered_user).first()
            assert session_row.revoked_at is not None
            assert session_row.revoked_reason == "logout"

        # Same still-unexpired access token must now be rejected — this is
        # the actual point of the blocklist loader, since a plain JWT
        # would otherwise stay valid until its own expiry regardless of
        # /logout.
        resp = client.get("/api/v1/auth/me", headers=headers)
        assert resp.status_code == 401

    def test_refresh_carries_same_session_forward(self, app, client, registered_user):
        resp = client.post("/api/v1/auth/login", json={
            "email": "sessiontest", "password": "TestPass123!",
        })
        refresh_token = resp.get_json()["refresh_token"]

        with app.app_context():
            from app.models.user_session import UserSession
            session_count_before = UserSession.query.filter_by(user_id=registered_user).count()

        resp = client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {refresh_token}"})
        assert resp.status_code == 200
        new_access_token = resp.get_json()["access_token"]

        with app.app_context():
            from app.models.user_session import UserSession
            # Refresh must NOT create a second session row for the same login.
            assert UserSession.query.filter_by(user_id=registered_user).count() == session_count_before

        # The refreshed access token must map to the same (still valid) session.
        resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access_token}"})
        assert resp.status_code == 200

    def test_admin_can_list_and_revoke_session(self, app, client, registered_user):
        client.post("/api/v1/auth/login", json={"email": "sessiontest", "password": "TestPass123!"})

        with app.app_context():
            from app.extensions import db
            from app.models.user import User, Role
            from flask_jwt_extended import create_access_token

            role = Role.query.filter_by(name="admin").first()
            admin = User(username="sessionadmin", email="sessionadmin@example.com", role_id=role.id,
                         approval_status="approved", is_super_admin=True)
            admin.set_password("TestPass123!")
            db.session.add(admin)
            db.session.commit()
            admin_token = create_access_token(identity=str(admin.id))

        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        resp = client.get("/api/v1/admin/sessions", headers=admin_headers)
        assert resp.status_code == 200
        sessions = resp.get_json()["sessions"]
        target = next(s for s in sessions if s["user_id"] == registered_user)
        assert target["is_active"] is True

        resp = client.post(f"/api/v1/admin/sessions/{target['id']}/revoke", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.get_json()["is_active"] is False

    def test_session_timeout_config_validation(self, app, client):
        with app.app_context():
            from app.extensions import db
            from app.models.user import User, Role
            from flask_jwt_extended import create_access_token

            role = Role.query.filter_by(name="admin").first()
            admin = User(username="cfgadmin", email="cfgadmin@example.com", role_id=role.id,
                         approval_status="approved", is_super_admin=True)
            admin.set_password("TestPass123!")
            db.session.add(admin)
            db.session.commit()
            admin_token = create_access_token(identity=str(admin.id))

        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = client.put("/api/v1/admin/platform-config", headers=headers,
                           json={"session_timeout_minutes": 60})
        assert resp.status_code == 200
        assert resp.get_json()["session_timeout_minutes"] == 60

        resp = client.put("/api/v1/admin/platform-config", headers=headers,
                           json={"session_timeout_minutes": 1})
        assert resp.status_code == 400
