"""Integration test: real Flask app + in-memory SQLite DB, proving
AuditLog.record()'s super-admin suppression and the new selective-delete
endpoint actually work end-to-end through the real HTTP routes — not
just that the config field exists.
"""
import pytest


@pytest.fixture
def super_admin_headers(app, client):
    with app.app_context():
        from app.extensions import db
        from app.models.user import User, Role
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="admin").first()
        admin = User(username="auditadmin", email="auditadmin@example.com", role_id=role.id,
                     approval_status="approved", is_super_admin=True)
        admin.set_password("TestPass123!")
        db.session.add(admin)
        db.session.commit()
        token = create_access_token(identity=str(admin.id))
    return {"Authorization": f"Bearer {token}"}


class TestAuditLogSuperAdminSuppression:
    def test_super_admin_login_not_logged_by_default(self, app, client):
        with app.app_context():
            from app.extensions import db
            from app.models.user import User, Role

            role = Role.query.filter_by(name="admin").first()
            admin = User(username="quietadmin", email="quietadmin@example.com", role_id=role.id,
                         approval_status="approved", is_super_admin=True)
            admin.set_password("TestPass123!")
            db.session.add(admin)
            db.session.commit()

        resp = client.post("/api/v1/auth/login", json={"email": "quietadmin", "password": "TestPass123!"})
        assert resp.status_code == 200

        with app.app_context():
            from app.models.audit import AuditLog
            from app.models.user import User
            admin = User.query.filter_by(username="quietadmin").first()
            assert AuditLog.query.filter_by(user_id=admin.id, action="login").count() == 0

    def test_regular_user_login_always_logged(self, app, client):
        with app.app_context():
            from app.extensions import db
            from app.models.user import User, Role

            role = Role.query.filter_by(name="free").first()
            user = User(username="regularuser", email="regularuser@example.com", role_id=role.id,
                        approval_status="approved")
            user.set_password("TestPass123!")
            db.session.add(user)
            db.session.commit()

        resp = client.post("/api/v1/auth/login", json={"email": "regularuser", "password": "TestPass123!"})
        assert resp.status_code == 200

        with app.app_context():
            from app.models.audit import AuditLog
            from app.models.user import User
            user = User.query.filter_by(username="regularuser").first()
            assert AuditLog.query.filter_by(user_id=user.id, action="login").count() == 1

    def test_enabling_setting_logs_super_admin_too(self, app, client, super_admin_headers):
        resp = client.put("/api/v1/admin/platform-config", headers=super_admin_headers,
                           json={"audit_log_super_admins": True})
        assert resp.status_code == 200
        assert resp.get_json()["audit_log_super_admins"] is True

        with app.app_context():
            from app.extensions import db
            from app.models.user import User, Role

            role = Role.query.filter_by(name="admin").first()
            admin = User(username="loudadmin", email="loudadmin@example.com", role_id=role.id,
                         approval_status="approved", is_super_admin=True)
            admin.set_password("TestPass123!")
            db.session.add(admin)
            db.session.commit()

        resp = client.post("/api/v1/auth/login", json={"email": "loudadmin", "password": "TestPass123!"})
        assert resp.status_code == 200

        with app.app_context():
            from app.models.audit import AuditLog
            from app.models.user import User
            admin = User.query.filter_by(username="loudadmin").first()
            assert AuditLog.query.filter_by(user_id=admin.id, action="login").count() == 1


class TestAuditLogSelectiveDelete:
    def test_delete_specific_ids_leaves_others_intact(self, app, client, super_admin_headers):
        with app.app_context():
            from app.extensions import db
            from app.models.audit import AuditLog

            AuditLog.query.delete()
            db.session.commit()
            rows = [AuditLog(action=f"test_action_{i}", status="success") for i in range(3)]
            db.session.add_all(rows)
            db.session.commit()
            ids = [r.id for r in rows]

        resp = client.get("/api/v1/admin/audit-logs", headers=super_admin_headers)
        assert resp.status_code == 200
        assert resp.get_json()["total"] == 3

        resp = client.delete("/api/v1/admin/audit-logs", headers=super_admin_headers,
                              json={"ids": [ids[0], ids[1]]})
        assert resp.status_code == 200
        assert "2" in resp.get_json()["message"]

        with app.app_context():
            from app.models.audit import AuditLog
            remaining = AuditLog.query.all()
            assert len(remaining) == 1
            assert remaining[0].id == ids[2]

    def test_delete_with_no_body_clears_everything(self, app, client, super_admin_headers):
        with app.app_context():
            from app.extensions import db
            from app.models.audit import AuditLog

            AuditLog.query.delete()
            db.session.add(AuditLog(action="test_action", status="success"))
            db.session.commit()

        resp = client.delete("/api/v1/admin/audit-logs", headers=super_admin_headers)
        assert resp.status_code == 200

        with app.app_context():
            from app.models.audit import AuditLog
            assert AuditLog.query.count() == 0
