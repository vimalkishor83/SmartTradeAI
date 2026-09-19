from datetime import datetime
from app.extensions import db


class VisitorLog(db.Model):
    """One row per distinct (ip_address, user_agent) pair seen on the
    public homepage — not one row per visit. Lets the security-alert hook
    in app/__init__.py tell a genuinely new IP or a new device on an
    already-known IP apart from a repeat visit, instead of re-alerting on
    every request past a short cooldown (see _register_security_visit_alerts).
    """
    __tablename__ = "visitor_logs"
    __table_args__ = (
        db.UniqueConstraint("ip_address", "user_agent", name="uq_visitor_logs_ip_ua"),
        db.Index("ix_visitor_logs_ip_address", "ip_address"),
    )

    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(50), nullable=False)
    user_agent = db.Column(db.String(500))
    location = db.Column(db.String(200))
    first_seen_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    visit_count = db.Column(db.Integer, default=1, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent or "",
            "location": self.location or "",
            "first_seen_at": self.first_seen_at.isoformat() if self.first_seen_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "visit_count": self.visit_count,
        }
