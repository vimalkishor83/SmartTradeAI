from datetime import datetime
from app.extensions import db


class EconomicEvent(db.Model):
    __tablename__ = "economic_events"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    country = db.Column(db.String(50))
    currency = db.Column(db.String(10))
    impact = db.Column(db.String(20))  # high, medium, low
    forecast = db.Column(db.String(50))
    previous = db.Column(db.String(50))
    actual = db.Column(db.String(50))
    event_time = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "country": self.country,
            "currency": self.currency,
            "impact": self.impact,
            "forecast": self.forecast,
            "previous": self.previous,
            "actual": self.actual,
            "event_time": self.event_time.isoformat() if self.event_time else None,
        }
