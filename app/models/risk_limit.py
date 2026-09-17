"""Per-user portfolio limits enforced before an order mutation."""

from datetime import datetime

from app.extensions import db


class RiskLimit(db.Model):
    __tablename__ = "risk_limits"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True, index=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    max_daily_loss = db.Column(db.Numeric(24, 8), nullable=False, default=0)
    max_drawdown_pct = db.Column(db.Numeric(10, 4), nullable=False, default=0)
    max_total_exposure = db.Column(db.Numeric(24, 8), nullable=False, default=0)
    max_correlated_exposure = db.Column(db.Numeric(24, 8), nullable=False, default=0)
    max_open_risk = db.Column(db.Numeric(24, 8), nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        def number(value):
            return float(value or 0)

        return {
            "enabled": bool(self.enabled),
            "max_daily_loss": number(self.max_daily_loss),
            "max_drawdown_pct": number(self.max_drawdown_pct),
            "max_total_exposure": number(self.max_total_exposure),
            "max_correlated_exposure": number(self.max_correlated_exposure),
            "max_open_risk": number(self.max_open_risk),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
