from datetime import datetime
from app.extensions import db


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(100), nullable=False)
    resource = db.Column(db.String(100))
    resource_id = db.Column(db.String(50))
    details = db.Column(db.JSON, default=dict)
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(500))
    status = db.Column(db.String(20), default="success")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship("User")

    @classmethod
    def record(cls, user_id, action, resource=None, resource_id=None, status="success",
               ip_address=None, user_agent=None, details=None):
        """Single entry point for writing an audit row — every call site
        should go through this rather than `AuditLog(...)` directly, so
        the admin's "log super admin actions too" setting (off by
        default — super admins don't audit-log their own activity unless
        deliberately turned on) is enforced in exactly one place instead
        of duplicated at every call site (auth login/logout, admin user
        actions, broker credential connects, ...). A None user_id (e.g. a
        failed login against an identifier that isn't a real account)
        has no super admin to suppress, so it's always logged — those are
        exactly the events most worth keeping.

        Returns the created row, or None if it was suppressed.
        """
        if user_id is not None:
            try:
                from app.services.platform_config import get_platform_config
                if not get_platform_config().get("audit_log_super_admins", False):
                    from app.models.user import User
                    actor = User.query.get(user_id)
                    if actor and actor.is_super_admin:
                        return None
            except Exception:
                pass  # never let the suppression check itself block real logging

        log = cls(
            user_id=user_id, action=action, resource=resource, resource_id=resource_id,
            status=status, ip_address=ip_address, user_agent=user_agent, details=details or {},
        )
        db.session.add(log)
        db.session.commit()
        return log

    def to_dict(self):
        return {
            "id": self.id,
            "user": self.user.username if self.user else "system",
            "action": self.action,
            "resource": self.resource or "—",
            "resource_id": self.resource_id or "",
            "status": self.status or "success",
            "ip_address": self.ip_address or "—",
            "created_at": self.created_at.isoformat(),
        }


class SystemLog(db.Model):
    __tablename__ = "system_logs"

    id = db.Column(db.Integer, primary_key=True)
    level = db.Column(db.String(10), nullable=False, index=True)
    module = db.Column(db.String(100))
    message = db.Column(db.Text, nullable=False)
    details = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "level": self.level,
            "module": self.module,
            "message": self.message,
            "created_at": self.created_at.isoformat(),
        }
