from datetime import datetime
from app.extensions import db


class TelegramAlertChannel(db.Model):
    """A named Telegram group destination scoped to specific markets, each
    with its own category switches — e.g. a "Crypto Signals" group that
    only wants new-signal + rating-change alerts, and a separate "Forex &
    Stocks" group that wants signal-closed too. Replaces the single global
    group destination: different markets legitimately want different
    audiences and different alert mixes, not one group getting everything
    for every market.

    Only carries the categories that are meaningful as a shared broadcast
    (signal, signal_closed, rating_change) — watchlist and protective-order
    alerts are about one specific user's own watchlist item or open
    position, so those only ever go out as individual DMs, gated by
    PlatformConfig.telegram_watchlist_individual_markets /
    telegram_protective_order_individual_markets, never a channel. See
    notification_tasks.fire_signal_alerts / check_rating_changes
    (channels) vs data_tasks.check_watchlist_alerts /
    protective_order_tasks._notify_trigger (always individual) for the
    two delivery paths this splits into.

    Distinct from PlatformConfig's own per-category
    telegram_<category>_group_markets fields, which are the first gate
    applied before any channel is even considered here (and
    telegram_<category>_individual_markets is the separate, independent
    gate for each subscriber's own personal Telegram alerts, since those
    aren't organized into channels at all — one person, one chat)."""
    __tablename__ = "telegram_alert_channels"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    group_chat_id = db.Column(db.String(64), nullable=False)
    # Empty list = every market (post the global PlatformConfig market gate).
    markets = db.Column(db.JSON, default=list)
    # Empty list = every timeframe — e.g. a "Scalpers" channel can watch only
    # 1m/5m signals while a "Swing" channel watches only 4h/1d/1w, out of the
    # same market and category toggles.
    timeframes = db.Column(db.JSON, default=list)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    alerts_signal           = db.Column(db.Boolean, default=True, nullable=False)
    alerts_signal_closed    = db.Column(db.Boolean, default=True, nullable=False)
    alerts_rating_change    = db.Column(db.Boolean, default=False, nullable=False)
    rating_change_sensitivity = db.Column(db.String(20), default="cross_zone", nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def matches(self, market: str, category: str, timeframe: str | None = None) -> bool:
        """Whether this channel should receive an alert of `category`
        (one of the alerts_* column names, minus the prefix) for `market`
        on `timeframe`. `timeframe=None` skips that check (used by callers
        that have no single timeframe to test, if any are ever added)."""
        if not self.is_active:
            return False
        if self.markets and market not in self.markets:
            return False
        if timeframe and self.timeframes and timeframe not in self.timeframes:
            return False
        return bool(getattr(self, f"alerts_{category}", False))

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "group_chat_id": self.group_chat_id,
            "markets": self.markets or [],
            "timeframes": self.timeframes or [],
            "is_active": self.is_active,
            "alerts_signal": self.alerts_signal,
            "alerts_signal_closed": self.alerts_signal_closed,
            "alerts_rating_change": self.alerts_rating_change,
            "rating_change_sensitivity": self.rating_change_sensitivity,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
