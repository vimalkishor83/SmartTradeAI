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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "user": self.user.username if self.user else "system",
            "action": self.action,
            "resource": self.resource,
            "status": self.status,
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat(),
        }


class SystemLog(db.Model):
    __tablename__ = "system_logs"

    id = db.Column(db.Integer, primary_key=True)
    level = db.Column(db.String(10), nullable=False)  # INFO, WARNING, ERROR, CRITICAL
    module = db.Column(db.String(100))
    message = db.Column(db.Text, nullable=False)
    details = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "level": self.level,
            "module": self.module,
            "message": self.message,
            "created_at": self.created_at.isoformat(),
        }
