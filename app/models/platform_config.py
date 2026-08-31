from datetime import datetime
from app.extensions import db

DEFAULT_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"]


class PlatformConfig(db.Model):
    """Singleton row for admin-managed, platform-wide display defaults —
    which sidebar nav items are visible, and the canonical timeframe list."""
    __tablename__ = "platform_config"

    id = db.Column(db.Integer, primary_key=True)
    disabled_nav_items = db.Column(db.JSON, default=list)
    timeframes = db.Column(db.JSON, default=lambda: list(DEFAULT_TIMEFRAMES))
    # A Telegram *group* chat's ID — distinct from any individual user's own
    # telegram_chat_id (User model). Alerts sent here use the shared
    # platform bot (TELEGRAM_BOT_TOKEN), never a user's own bot token, since
    # a group isn't any one person's account. Blank/null = disabled, no
    # separate on/off flag needed.
    telegram_group_chat_id = db.Column(db.String(64))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    @classmethod
    def get_singleton(cls):
        row = cls.query.get(1)
        if not row:
            row = cls(id=1, disabled_nav_items=[], timeframes=list(DEFAULT_TIMEFRAMES))
            db.session.add(row)
            db.session.commit()
        return row

    def to_dict(self):
        return {
            "disabled_nav_items": self.disabled_nav_items or [],
            "timeframes": self.timeframes or list(DEFAULT_TIMEFRAMES),
            "telegram_group_chat_id": self.telegram_group_chat_id or "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
