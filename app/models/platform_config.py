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
    # Which Asset.MARKETS values are allowed to alert on Telegram at all —
    # checked before any per-category toggle below. Null/empty list means
    # "every market", not "no markets", so a fresh install (or an admin who
    # never touches this field) doesn't silently lose every alert.
    telegram_alert_markets = db.Column(db.JSON, default=list)

    # Per-category kill switches for Telegram delivery — apply to BOTH the
    # per-user sends and the group broadcast alike, since both draw from the
    # same underlying alert events. All default True except rating-change,
    # which is new and opt-in until an admin deliberately turns it on.
    telegram_alerts_signal           = db.Column(db.Boolean, default=True, nullable=False)
    telegram_alerts_signal_closed    = db.Column(db.Boolean, default=True, nullable=False)
    telegram_alerts_watchlist        = db.Column(db.Boolean, default=True, nullable=False)
    telegram_alerts_protective_order = db.Column(db.Boolean, default=True, nullable=False)
    telegram_alerts_rating_change    = db.Column(db.Boolean, default=False, nullable=False)
    # How big a rating swing (EMA 9/21 MTF's Strong Sell..Strong Buy scale)
    # counts as alert-worthy — see _is_ratingchange_alertworthy in
    # notification_tasks.py for what each value actually does.
    telegram_rating_change_sensitivity = db.Column(db.String(20), default="cross_zone", nullable=False)
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
            "telegram_alert_markets": self.telegram_alert_markets or [],
            "telegram_alerts_signal": self.telegram_alerts_signal,
            "telegram_alerts_signal_closed": self.telegram_alerts_signal_closed,
            "telegram_alerts_watchlist": self.telegram_alerts_watchlist,
            "telegram_alerts_protective_order": self.telegram_alerts_protective_order,
            "telegram_alerts_rating_change": self.telegram_alerts_rating_change,
            "telegram_rating_change_sensitivity": self.telegram_rating_change_sensitivity or "cross_zone",
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
