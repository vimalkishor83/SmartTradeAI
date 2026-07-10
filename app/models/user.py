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
    name = db.Column(db.String(50), unique=True, nullable=False)  # free, premium, admin
    price = db.Column(db.Float, default=0.0)
    features = db.Column(db.JSON, default=list)
    signal_delay_minutes = db.Column(db.Integer, default=0)
    max_watchlist = db.Column(db.Integer, default=10)
    max_alerts = db.Column(db.Integer, default=5)
    backtesting_enabled = db.Column(db.Boolean, default=False)
    ai_enabled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    users = db.relationship("User", backref="subscription", lazy="dynamic")


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

    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    subscription_id = db.Column(db.Integer, db.ForeignKey("subscriptions.id"))

    is_active = db.Column(db.Boolean, default=True)
    is_verified = db.Column(db.Boolean, default=False)
    # "pending" (self-registered, awaiting admin review), "approved" (full
    # access), "rejected" (blocked). Admin-created users are auto-approved.
    approval_status = db.Column(db.String(20), default="approved", nullable=False)
    email_notifications = db.Column(db.Boolean, default=True)
    telegram_chat_id = db.Column(db.String(100))
    telegram_enabled = db.Column(db.Boolean, default=False)
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

    @property
    def full_name(self):
        return f"{self.first_name or ''} {self.last_name or ''}".strip() or self.username

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role.name if self.role else None,
            "subscription": self.subscription.name if self.subscription else "free",
            "is_active": self.is_active,
            "approval_status": self.approval_status,
            "theme": self.theme,
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
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    asset_id   = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    enabled    = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "asset_id", name="uq_user_asset"),)
