from datetime import datetime
from app.extensions import db


class AutoGenerateConfig(db.Model):
    """Singleton row persisting Auto-Generate signal scheduler settings."""
    __tablename__ = "auto_generate_config"

    id                  = db.Column(db.Integer, primary_key=True)
    running             = db.Column(db.Boolean, default=False)
    asset_ids           = db.Column(db.JSON, default=list)
    markets             = db.Column(db.JSON, default=list)
    timeframes          = db.Column(db.JSON, default=lambda: ["1h"])
    signal_filter       = db.Column(db.String(20), default="all")
    min_confidence      = db.Column(db.Float, default=0)
    max_per_run         = db.Column(db.Integer, default=0)
    interval_minutes    = db.Column(db.Integer, default=5)
    telegram_on_signal  = db.Column(db.Boolean, default=True)
    updated_at          = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "running":            self.running,
            "asset_ids":          self.asset_ids or [],
            "markets":            self.markets or [],
            "timeframes":         self.timeframes or ["1h"],
            "signal_filter":      self.signal_filter,
            "min_confidence":     self.min_confidence,
            "max_per_run":        self.max_per_run,
            "interval_minutes":   self.interval_minutes,
            "telegram_on_signal": self.telegram_on_signal,
        }
