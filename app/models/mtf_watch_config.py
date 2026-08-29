from datetime import datetime
from app.extensions import db

# Shown when a user has no saved config yet — a sensible set of majors so
# the "Common Coins" MTF status view isn't empty on first visit.
DEFAULT_MTF_WATCH_SYMBOLS = ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD", "DOGEUSD", "ADAUSD", "LINKUSD"]


class MtfWatchConfig(db.Model):
    """A user's configurable list of Delta symbols for the MTF Scanner's
    "Common Coins" status view — one row per user (unlike SavedScreen, which
    allows multiple named configs, this is a single always-on list the user
    edits in place, closer to a personal watch panel than a saved preset)."""
    __tablename__ = "mtf_watch_configs"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True, index=True)
    symbols    = db.Column(db.JSON, nullable=False, default=list)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "symbols": self.symbols or [],
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
