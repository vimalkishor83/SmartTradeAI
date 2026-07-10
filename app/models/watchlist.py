from datetime import datetime
from app.extensions import db


class Watchlist(db.Model):
    __tablename__ = "watchlists"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255))
    is_pinned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship("WatchlistItem", backref="watchlist", lazy="dynamic", cascade="all, delete-orphan")


class WatchlistItem(db.Model):
    __tablename__ = "watchlist_items"

    id = db.Column(db.Integer, primary_key=True)
    watchlist_id = db.Column(db.Integer, db.ForeignKey("watchlists.id"), nullable=False)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    alert_price = db.Column(db.Float)
    # Price at the moment the alert was set — lets the checker fire only on
    # an actual *crossing* (price moves from one side of alert_price to the
    # other, relative to where it started) instead of firing unconditionally
    # the moment current_price is compared against alert_price at all.
    alert_set_at_price = db.Column(db.Float)
    notes = db.Column(db.String(255))
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    asset = db.relationship("Asset")
