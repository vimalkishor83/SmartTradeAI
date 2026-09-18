from datetime import datetime

from app.extensions import db

# Keep in sync with the categories notification_tasks.py actually sends:
# signal alerts, signal-close (TP/SL) alerts, rating-change alerts,
# watchlist alerts, and protective-order alerts. Security/news are not
# personal categories and are never covered by this table.
TELEGRAM_ALERT_CATEGORIES = [
    "signal",
    "signal_closed",
    "rating_change",
    "watchlist",
    "protective_order",
]


class TelegramUserPreference(db.Model):
    """Per-user override for which personal Telegram alerts a user receives.

    This sits on top of (never replaces) PlatformConfig's existing
    per-category, per-market gates — those remain the platform-wide
    kill-switch an admin uses to turn a category off for everyone or for
    a whole market. This table lets an admin additionally narrow one
    specific user's personal alerts further, e.g. "this user only wants
    crypto signal alerts, not rating-change or watchlist alerts."

    ``None`` on categories/markets/asset_ids means "no per-user
    restriction beyond the platform-wide gate" — the same
    None-means-everything convention already used by
    TelegramIndividualSignalLimit, so a user with no row here (or a row
    with every field left None) behaves exactly as before this feature
    existed.
    """

    __tablename__ = "telegram_user_preferences"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)

    categories = db.Column(db.JSON, nullable=True, default=None)
    markets = db.Column(db.JSON, nullable=True, default=None)
    asset_ids = db.Column(db.JSON, nullable=True, default=None)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    user = db.relationship("User", foreign_keys=[user_id], backref=db.backref(
        "telegram_preference", uselist=False, cascade="all, delete-orphan",
    ))

    def allows(self, category, market=None, asset_id=None):
        if self.categories is not None and category not in self.categories:
            return False
        if market is not None and self.markets is not None and market not in self.markets:
            return False
        if asset_id is not None and self.asset_ids is not None:
            try:
                asset_id = int(asset_id)
            except (TypeError, ValueError):
                return False
            if asset_id not in {int(value) for value in self.asset_ids}:
                return False
        return True

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "categories": self.categories,
            "markets": self.markets,
            "asset_ids": self.asset_ids,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "updated_by": self.updated_by,
        }
