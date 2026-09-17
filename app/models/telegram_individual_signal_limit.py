from datetime import datetime

from app.extensions import db


class TelegramIndividualSignalLimit(db.Model):
    """Singleton allow-list for personal signal-related Telegram delivery.

    ``None`` means all active assets/timeframes, while an empty list means
    none. This keeps an explicit "send nothing" state separate from the
    backwards-compatible default of allowing everything.
    """

    __tablename__ = "telegram_individual_signal_limits"

    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    asset_ids = db.Column(db.JSON, nullable=True, default=None)
    timeframes = db.Column(db.JSON, nullable=True, default=None)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    @classmethod
    def get_singleton(cls):
        row = cls.query.get(1)
        if not row:
            row = cls(id=1, enabled=True, asset_ids=None, timeframes=None)
            db.session.add(row)
            db.session.commit()
        return row

    def allows(self, asset_id, timeframe):
        if not self.enabled:
            return False
        if self.asset_ids is not None and int(asset_id) not in {int(value) for value in self.asset_ids}:
            return False
        if self.timeframes is not None and timeframe not in self.timeframes:
            return False
        return True

    def to_dict(self):
        return {
            "enabled": bool(self.enabled),
            "asset_ids": self.asset_ids,
            "timeframes": self.timeframes,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "updated_by": self.updated_by,
        }
