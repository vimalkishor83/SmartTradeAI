from datetime import datetime
from app.extensions import db


class APIConfig(db.Model):
    __tablename__ = "api_configs"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    provider = db.Column(db.String(50))  # binance, alphavantage, zerodha, etc.
    market = db.Column(db.String(30))
    api_key_encrypted = db.Column(db.Text)
    api_secret_encrypted = db.Column(db.Text)
    base_url = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True)
    rate_limit = db.Column(db.Integer, default=60)
    last_used = db.Column(db.DateTime)
    error_count = db.Column(db.Integer, default=0)
    config = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self, reveal_keys=False):
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "market": self.market,
            "base_url": self.base_url,
            "is_active": self.is_active,
            "rate_limit": self.rate_limit,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "error_count": self.error_count,
        }
