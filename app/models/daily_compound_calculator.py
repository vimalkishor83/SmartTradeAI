from datetime import datetime
from app.extensions import db


class DailyCompoundCalculation(db.Model):
    """Saved scenarios for the internal Daily Compound Calculator utility
    (super-admin only, see app/modules/daily_compound_calculator.py).

    Reimplements the standalone Daily Compound Calculator Flutter app's
    local saved_calculations SQLite table (that app's source is lost —
    see D:\\Claude\\Documentation\\daily_compound_calculator_Documentation
    for its surviving spec) as a shared, DB-backed table so any super
    admin can save/reopen a scenario. The generated day/month/year
    schedule is deliberately NOT stored here, matching the original
    app's own design: only the six raw inputs are persisted, and the
    full schedule is always regenerated on demand from
    app.services.daily_compound.engine.calculate().
    """
    __tablename__ = "daily_compound_calculations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    principal = db.Column(db.Float, nullable=False)
    rate_percent = db.Column(db.Float, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    duration_value = db.Column(db.Integer, nullable=False)
    duration_unit = db.Column(db.String(10), nullable=False)   # days, months, years
    frequency = db.Column(db.String(12), nullable=False)       # daily, weekly, monthly, quarterly, half_yearly, yearly
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    created_by = db.relationship("User")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "principal": self.principal,
            "rate_percent": self.rate_percent,
            "start_date": self.start_date.isoformat(),
            "duration_value": self.duration_value,
            "duration_unit": self.duration_unit,
            "frequency": self.frequency,
            "created_by": self.created_by.username if self.created_by else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
