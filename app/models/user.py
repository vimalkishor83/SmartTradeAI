from datetime import datetime
from app.extensions import db, bcrypt


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(255))
    permissions = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    users = db.relationship("User", backref="role", lazy="dynamic")

    def __repr__(self):
        return f"<Role {self.name}>"


class Subscription(db.Model):
    __tablename__ = "subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # free, basic, premium, pro, admin
    # Ordinal rank of this plan in the free->basic->premium->pro ladder, so
    # gating can express "requires at least tier N" (see
    # app/auth/decorators.py:min_tier_required) instead of hardcoding plan
    # names at every call site. Admin is intentionally above the paid ladder
    # (99) so it always satisfies any min_tier_required check. Two plans
    # should never share a tier_level — order is meaningful, not just a tag.
    tier_level = db.Column(db.Integer, default=0, nullable=False)
    price = db.Column(db.Float, default=0.0)
    features = db.Column(db.JSON, default=list)
    signal_delay_minutes = db.Column(db.Integer, default=0)
    max_watchlist = db.Column(db.Integer, default=10)
    max_alerts = db.Column(db.Integer, default=5)
    backtesting_enabled = db.Column(db.Boolean, default=False)
    ai_enabled = db.Column(db.Boolean, default=False)
    advanced_charts_enabled = db.Column(db.Boolean, default=False)
    broker_connect_enabled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    users = db.relationship("User", backref="subscription", lazy="dynamic")


class Broker(db.Model):
    """Admin-managed list of supported brokers, shown as a dropdown on
    registration. Each broker can carry its own account-opening referral
    link (e.g. an affiliate signup URL) shown to users who don't have an
    account yet, distinct from the platform-wide ReferralCode discount
    system — a Broker entry is "which broker are you with / want to join",
    a ReferralCode is "what code unlocks a free plan tier"."""
    __tablename__ = "brokers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    referral_link = db.Column(db.String(500))  # affiliate/account-opening URL, optional
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    users = db.relationship("User", backref="broker", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "referral_link": self.referral_link,
            "is_active": self.is_active,
            "sort_order": self.sort_order,
        }

    def __repr__(self):
        return f"<Broker {self.name}>"


class ReferralCode(db.Model):
    """Partner/broker referral codes. A valid, active code grants the
    referred_role (typically premium) instead of the default free tier on
    signup, and can optionally be scoped to a specific broker."""
    __tablename__ = "referral_codes"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False, index=True)
    broker_name = db.Column(db.String(80))
    description = db.Column(db.String(255))
    referred_role_id = db.Column(db.Integer, db.ForeignKey("roles.id"))
    referred_subscription_id = db.Column(db.Integer, db.ForeignKey("subscriptions.id"))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    max_uses = db.Column(db.Integer)  # NULL = unlimited
    uses_count = db.Column(db.Integer, default=0, nullable=False)
    expires_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    referred_role = db.relationship("Role", foreign_keys=[referred_role_id])
    referred_subscription = db.relationship("Subscription", foreign_keys=[referred_subscription_id])
    users = db.relationship("User", backref="referral_code", lazy="dynamic")

    def is_valid(self):
        if not self.is_active:
            return False
        if self.expires_at and self.expires_at < datetime.utcnow():
            return False
        if self.max_uses is not None and self.uses_count >= self.max_uses:
            return False
        return True

    def __repr__(self):
        return f"<ReferralCode {self.code}>"


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(80))
    last_name = db.Column(db.String(80))
    phone = db.Column(db.String(20))
    avatar = db.Column(db.String(255))
    broker_id = db.Column(db.Integer, db.ForeignKey("brokers.id"), nullable=True)  # which broker (dropdown)
    broker_account_id = db.Column(db.String(80))  # the user's own account/client ID with that broker
    referral_code_id = db.Column(db.Integer, db.ForeignKey("referral_codes.id"), nullable=True)

    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    subscription_id = db.Column(db.Integer, db.ForeignKey("subscriptions.id"))
    # Distinguishes the small set of admins who can actually change things
    # (create/edit/delete users, edit platform config, API configs, etc.)
    # from regular "admin" role holders who can view every admin page but
    # not mutate anything — see super_admin_required in auth/decorators.py.
    # A regular admin account is not automatically trusted with this; it is
    # only ever set True by another super admin (or the initial seed).
    is_super_admin = db.Column(db.Boolean, default=False, nullable=False)

    is_active = db.Column(db.Boolean, default=True)
    is_verified = db.Column(db.Boolean, default=False)
    # "pending" (self-registered, awaiting admin review), "approved" (full
    # access), "rejected" (blocked). Admin-created users are auto-approved.
    approval_status = db.Column(db.String(20), default="approved", nullable=False)
    email_notifications = db.Column(db.Boolean, default=True)
    telegram_chat_id = db.Column(db.String(100))
    telegram_enabled = db.Column(db.Boolean, default=False)
    # Each user's own bot token, not one shared TELEGRAM_BOT_TOKEN for the
    # whole platform — a user who already runs their own bot (or doesn't
    # want their alerts flowing through a bot they don't control) can set
    # it themselves. Encrypted at rest via the same Fernet helper broker
    # API credentials use (app/services/security/crypto.py), since a bot
    # token is just as capable of sending-as-you as any other API secret.
    telegram_bot_token_encrypted = db.Column(db.Text)
    push_enabled = db.Column(db.Boolean, default=False)
    theme = db.Column(db.String(10), default="dark")
    account_size = db.Column(db.Float, default=100000.0)
    risk_per_trade_pct = db.Column(db.Float, default=1.0)
    min_confidence_filter = db.Column(db.Integer, default=60)

    # Two-Factor Authentication
    totp_secret       = db.Column(db.String(64), nullable=True)
    totp_enabled      = db.Column(db.Boolean, default=False)
    totp_backup_codes = db.Column(db.Text, nullable=True)  # JSON list of hashed backup codes

    # Web Push subscription (JSON from browser PushSubscription.toJSON())
    push_subscription = db.Column(db.Text, nullable=True)

    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    watchlists = db.relationship("Watchlist", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    portfolios = db.relationship("Portfolio", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    notifications = db.relationship("Notification", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    backtests = db.relationship("Backtest", backref="user", lazy="dynamic", cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    def set_telegram_bot_token(self, plaintext: str):
        from app.services.security.crypto import encrypt_value
        self.telegram_bot_token_encrypted = encrypt_value(plaintext) if plaintext else ""

    def get_telegram_bot_token(self) -> str | None:
        """Decrypt this user's own bot token. Falls back to legacy plaintext
        if it doesn't look encrypted, matching APIConfig/UserBrokerCredential."""
        from app.services.security.crypto import decrypt_value, is_encrypted
        if not self.telegram_bot_token_encrypted:
            return None
        if not is_encrypted(self.telegram_bot_token_encrypted):
            return self.telegram_bot_token_encrypted
        return decrypt_value(self.telegram_bot_token_encrypted)

    @property
    def full_name(self):
        return f"{self.first_name or ''} {self.last_name or ''}".strip() or self.username

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "role": self.role.name if self.role else None,
            "role_id": self.role_id,
            "is_super_admin": self.is_super_admin,
            "subscription": self.subscription.name if self.subscription else "free",
            "subscription_id": self.subscription_id,
            "subscription_tier_level": self.subscription.tier_level if self.subscription else 0,
            "broker": self.broker.name if self.broker else None,
            "broker_account_id": self.broker_account_id,
            "referral_code": self.referral_code.code if self.referral_code else None,
            "is_active": self.is_active,
            "approval_status": self.approval_status,
            "is_verified": self.is_verified,
            "theme": self.theme,
            # Settings page reads all four of these to populate the
            # Notifications card on load — they were captured by PUT /me
            # correctly, but never actually sent back by this to_dict(), so
            # the toggle/fields silently reset to blank on every page visit
            # regardless of what was saved. has_telegram_bot_token mirrors
            # APIConfig's has_key/has_secret pattern: never return the
            # decrypted token itself, just whether one is on file.
            "email_notifications": self.email_notifications,
            "telegram_enabled": self.telegram_enabled,
            "telegram_chat_id": self.telegram_chat_id,
            "has_telegram_bot_token": bool(self.telegram_bot_token_encrypted),
            "account_size": self.account_size or 100000.0,
            "risk_per_trade_pct": self.risk_per_trade_pct or 1.0,
            "min_confidence_filter": self.min_confidence_filter if self.min_confidence_filter is not None else 60,
            "totp_enabled": self.totp_enabled,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self):
        return f"<User {self.username}>"


class UserAssetPreference(db.Model):
    """Stores which assets a user has selected for TA Summary / MTF Analysis."""
    __tablename__ = "user_asset_preferences"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    asset_id   = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    enabled    = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "asset_id", name="uq_user_asset"),)
