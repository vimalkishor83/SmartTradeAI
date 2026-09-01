"""Integration test: proves the new-IP-login alert still fires for a
super admin even when "log super admin actions" is off (the default) —
the actual regression this guards against. The alert used to read its
"have I seen this IP before" history from AuditLog, which stops
recording a super admin's own logins the moment that setting is off,
so the alert silently stopped firing for exactly the accounts it exists
to protect. It now reads from UserSession instead, which always records
every login regardless of that setting.
"""
import pytest
from unittest.mock import patch


@pytest.fixture
def super_admin_user(app):
    with app.app_context():
        from app.extensions import db
        from app.models.user import User, Role

        role = Role.query.filter_by(name="admin").first()
        admin = User(username="ipalertadmin", email="ipalertadmin@example.com", role_id=role.id,
                     approval_status="approved", is_super_admin=True,
                     telegram_enabled=True, telegram_chat_id="999")
        admin.set_password("TestPass123!")
        db.session.add(admin)
        db.session.commit()
        return admin.id


class TestNewIpLoginAlert:
    def test_fires_for_super_admin_even_with_audit_suppression_on(self, app, client, super_admin_user):
        with app.app_context():
            from app.models.platform_config import PlatformConfig
            from app.extensions import db
            row = PlatformConfig.get_singleton()
            # The default — super admin logins are NOT written to AuditLog.
            assert row.audit_log_super_admins is False
            row.telegram_alerts_new_ip_login = True
            db.session.commit()

        alert_calls = []
        with patch("app.tasks.notification_tasks.send_new_ip_login_alert",
                    side_effect=lambda *a, **k: alert_calls.append(a)):
            # First login from IP A — no prior history at all, so this
            # must NOT count as "new" (a first-ever login isn't anomalous).
            resp = client.post("/api/v1/auth/login",
                                json={"email": "ipalertadmin", "password": "TestPass123!"},
                                environ_base={"REMOTE_ADDR": "1.1.1.1"})
            assert resp.status_code == 200
            assert len(alert_calls) == 0

            # Second login, same IP — genuinely not new, must not alert.
            resp = client.post("/api/v1/auth/login",
                                json={"email": "ipalertadmin", "password": "TestPass123!"},
                                environ_base={"REMOTE_ADDR": "1.1.1.1"})
            assert resp.status_code == 200
            assert len(alert_calls) == 0

            # Third login, a NEW IP — this is the regression case: with
            # audit suppression on, the admin's logins never reached
            # AuditLog, so the old AuditLog-based check always saw zero
            # history and never fired. Must fire now.
            resp = client.post("/api/v1/auth/login",
                                json={"email": "ipalertadmin", "password": "TestPass123!"},
                                environ_base={"REMOTE_ADDR": "2.2.2.2"})
            assert resp.status_code == 200
            assert len(alert_calls) == 1
            assert alert_calls[0][1] == "2.2.2.2"

        with app.app_context():
            from app.models.audit import AuditLog
            # Confirms the regression's precondition actually held: this
            # admin's logins really were absent from AuditLog throughout.
            assert AuditLog.query.filter_by(user_id=super_admin_user, action="login").count() == 0
