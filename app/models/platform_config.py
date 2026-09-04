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

    # Per-category, per-delivery-level market lists — replaces a single
    # global market gate + a flat on/off toggle per category. Each field
    # is the list of Asset.MARKETS this category/level fires for; an empty
    # list means OFF for every market, NOT "every market" (unlike
    # TelegramAlertChannel.markets, which keeps the opposite convention —
    # these exist specifically so an admin can say "crypto signal alerts
    # go to individuals AND a group, forex signal alerts go to the group
    # only, gold gets neither" all from one row). No group list for
    # watchlist/protective_order: those alerts are about one specific
    # subscriber's own item/position, so they only ever make sense as an
    # individual DM, never a shared broadcast.
    telegram_signal_individual_markets           = db.Column(db.JSON, default=list)
    telegram_signal_group_markets                = db.Column(db.JSON, default=list)
    telegram_signal_closed_individual_markets    = db.Column(db.JSON, default=list)
    telegram_signal_closed_group_markets         = db.Column(db.JSON, default=list)
    telegram_rating_change_individual_markets    = db.Column(db.JSON, default=list)
    telegram_rating_change_group_markets         = db.Column(db.JSON, default=list)
    telegram_watchlist_individual_markets        = db.Column(db.JSON, default=list)
    telegram_protective_order_individual_markets = db.Column(db.JSON, default=list)

    # How big a rating swing (EMA 9/21 MTF's Strong Sell..Strong Buy scale)
    # counts as alert-worthy — see _is_ratingchange_alertworthy in
    # notification_tasks.py for what each value actually does.
    telegram_rating_change_sensitivity = db.Column(db.String(20), default="cross_zone", nullable=False)

    # How long a login stays valid before it's forced to re-authenticate,
    # in minutes, measured from login — not an idle timer, and not
    # extended by refreshing the access token (see UserSession.expires_at,
    # set once at login from this value). 1440 = 24h, matching this app's
    # previous fixed JWT_ACCESS_EXPIRES_HOURS-only behavior, now
    # admin-adjustable without an env var change/redeploy.
    session_timeout_minutes = db.Column(db.Integer, default=1440, nullable=False)

    # Security notification, not a trading alert — no market/individual-
    # group split applies. Sent to every super admin's own personal
    # Telegram chat (never a Group Channel, never the logged-in user's
    # own alerts) the moment a login uses an IP not seen for that account
    # before. See send_new_ip_login_alert() in notification_tasks.py.
    telegram_alerts_new_ip_login = db.Column(db.Boolean, default=True, nullable=False)

    # Off by default — a super admin's own logins/actions don't clutter
    # the audit trail unless deliberately turned on. See
    # AuditLog.record(), the single place this is actually enforced.
    audit_log_super_admins = db.Column(db.Boolean, default=False, nullable=False)

    # Off by default -- an experimental extra gate (SignalEngine.
    # _smc_order_block_gate) requiring price to be near an unmitigated
    # swing-structure order block before a signal fires, on top of the
    # existing EMA/ADX/DI/momentum gates. Unlike those, this hasn't run
    # through the same live-validated backtest sweep yet (SMC concepts are
    # notoriously discretionary to turn into deterministic rules), so it's
    # opt-in rather than always-on until there's real evidence either way.
    # Read by SignalEngine.generate_signal()/analyze() for both
    # Auto-Generate and Terminal live reads -- one flag controls both.
    smc_order_block_gate_enabled = db.Column(db.Boolean, default=False, nullable=False)

    # Same off-by-default, unvalidated-by-a-full-sweep status as the order
    # block gate above -- a separate toggle (not bundled with it) so the two
    # SMC concepts can be tested/enabled independently. See SignalEngine.
    # _smc_liquidity_sweep_gate.
    smc_liquidity_sweep_gate_enabled = db.Column(db.Boolean, default=False, nullable=False)

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
            "telegram_signal_individual_markets": self.telegram_signal_individual_markets or [],
            "telegram_signal_group_markets": self.telegram_signal_group_markets or [],
            "telegram_signal_closed_individual_markets": self.telegram_signal_closed_individual_markets or [],
            "telegram_signal_closed_group_markets": self.telegram_signal_closed_group_markets or [],
            "telegram_rating_change_individual_markets": self.telegram_rating_change_individual_markets or [],
            "telegram_rating_change_group_markets": self.telegram_rating_change_group_markets or [],
            "telegram_watchlist_individual_markets": self.telegram_watchlist_individual_markets or [],
            "telegram_protective_order_individual_markets": self.telegram_protective_order_individual_markets or [],
            "telegram_rating_change_sensitivity": self.telegram_rating_change_sensitivity or "cross_zone",
            "session_timeout_minutes": self.session_timeout_minutes or 1440,
            "telegram_alerts_new_ip_login": self.telegram_alerts_new_ip_login,
            "audit_log_super_admins": self.audit_log_super_admins,
            "smc_order_block_gate_enabled": self.smc_order_block_gate_enabled,
            "smc_liquidity_sweep_gate_enabled": self.smc_liquidity_sweep_gate_enabled,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
