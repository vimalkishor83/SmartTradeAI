from datetime import datetime
from app.extensions import db


class APIConfig(db.Model):
    __tablename__ = "api_configs"

    id               = db.Column(db.Integer, primary_key=True)
    name             = db.Column(db.String(100), unique=True, nullable=False)
    provider         = db.Column(db.String(50))
    market           = db.Column(db.String(30))
    api_key_encrypted    = db.Column(db.Text)
    api_secret_encrypted = db.Column(db.Text)
    access_token     = db.Column(db.Text)
    refresh_token    = db.Column(db.Text)
    base_url         = db.Column(db.String(500))
    websocket_url    = db.Column(db.String(500))
    auth_type        = db.Column(db.String(30), default="api_key")  # api_key, oauth, token, none
    is_active        = db.Column(db.Boolean, default=True)
    is_default       = db.Column(db.Boolean, default=False)
    status           = db.Column(db.String(20), default="active")   # active, paused, error
    connection_status= db.Column(db.String(20), default="unknown")  # ok, error, unknown
    priority         = db.Column(db.Integer, default=0)
    rate_limit       = db.Column(db.Integer, default=60)
    refresh_interval = db.Column(db.Integer, default=60)
    last_used        = db.Column(db.DateTime)
    last_sync        = db.Column(db.DateTime)
    last_latency_ms  = db.Column(db.Integer)
    error_count      = db.Column(db.Integer, default=0)
    config           = db.Column(db.JSON, default=dict)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    logs = db.relationship("APILog", backref="api_config", lazy="dynamic",
                           cascade="all, delete-orphan")

    MARKETS = ["crypto", "indian_stock", "us_stock", "forex", "commodity", "index"]

    PROVIDERS = {
        "crypto":       ["binance", "bybit", "okx", "kucoin", "delta_exchange", "coindcx", "bitget", "custom"],
        "indian_stock": ["angel_one", "zerodha", "upstox", "fyers", "groww", "dhan", "icici_direct", "kotak", "custom"],
        "us_stock":     ["alpaca", "interactive_brokers", "tradier", "td_ameritrade", "custom"],
        "forex":        ["oanda", "interactive_brokers", "custom"],
        "commodity":    ["yahoo", "twelve_data", "alpha_vantage", "custom"],
        "index":        ["yahoo", "alpha_vantage", "twelve_data", "finnhub", "polygon", "custom"],
        "data":         ["yahoo", "alpha_vantage", "twelve_data", "finnhub", "polygon", "tiingo", "iex_cloud", "custom"],
    }

    PROVIDER_DEFAULTS = {
        "binance":              {"base_url": "https://api.binance.com", "websocket_url": "wss://stream.binance.com:9443"},
        "delta_exchange":       {"base_url": "https://api.india.delta.exchange", "websocket_url": "wss://socket.india.delta.exchange"},
        "bybit":                {"base_url": "https://api.bybit.com",   "websocket_url": "wss://stream.bybit.com/v5/public/linear"},
        "okx":                  {"base_url": "https://www.okx.com",     "websocket_url": "wss://ws.okx.com:8443/ws/v5/public"},
        "kucoin":               {"base_url": "https://api.kucoin.com"},
        "angel_one":            {"base_url": "https://apiconnect.angelbroking.com"},
        "zerodha":              {"base_url": "https://api.kite.trade"},
        "upstox":               {"base_url": "https://api.upstox.com/v2"},
        "fyers":                {"base_url": "https://api.fyers.in/api/v2"},
        "alpaca":               {"base_url": "https://paper-api.alpaca.markets", "websocket_url": "wss://stream.data.alpaca.markets/v2/iex"},
        "interactive_brokers":  {"base_url": "https://localhost:5000/v1/api"},
        "yahoo":                {"base_url": "https://query1.finance.yahoo.com"},
        "alpha_vantage":        {"base_url": "https://www.alphavantage.co"},
        "twelve_data":          {"base_url": "https://api.twelvedata.com"},
        "finnhub":              {"base_url": "https://finnhub.io/api/v1"},
        "polygon":              {"base_url": "https://api.polygon.io"},
        "tiingo":               {"base_url": "https://api.tiingo.com"},
        "iex_cloud":            {"base_url": "https://cloud.iexapis.com/stable"},
    }

    def set_api_key(self, plaintext: str):
        from app.services.security.crypto import encrypt_value
        self.api_key_encrypted = encrypt_value(plaintext) if plaintext else ""

    def set_api_secret(self, plaintext: str):
        from app.services.security.crypto import encrypt_value
        self.api_secret_encrypted = encrypt_value(plaintext) if plaintext else ""

    def get_api_key(self) -> str | None:
        """Decrypt the stored key. Falls back to the raw stored value if it
        doesn't look encrypted (legacy plaintext rows created before
        encryption was added) so existing configs keep working."""
        from app.services.security.crypto import decrypt_value, is_encrypted
        if not self.api_key_encrypted:
            return None
        if not is_encrypted(self.api_key_encrypted):
            return self.api_key_encrypted
        return decrypt_value(self.api_key_encrypted)

    def get_api_secret(self) -> str | None:
        from app.services.security.crypto import decrypt_value, is_encrypted
        if not self.api_secret_encrypted:
            return None
        if not is_encrypted(self.api_secret_encrypted):
            return self.api_secret_encrypted
        return decrypt_value(self.api_secret_encrypted)

    def to_dict(self, reveal_keys=False):
        return {
            "id":               self.id,
            "name":             self.name,
            "provider":         self.provider,
            "market":           self.market,
            "base_url":         self.base_url,
            "websocket_url":    self.websocket_url,
            "auth_type":        self.auth_type,
            "is_active":        self.is_active,
            "is_default":       self.is_default,
            "status":           self.status,
            "connection_status":self.connection_status,
            "priority":         self.priority,
            "rate_limit":       self.rate_limit,
            "refresh_interval": self.refresh_interval,
            "last_used":        self.last_used.isoformat()  if self.last_used  else None,
            "last_sync":        self.last_sync.isoformat()  if self.last_sync  else None,
            "last_latency_ms":  self.last_latency_ms,
            "error_count":      self.error_count,
            "created_at":       self.created_at.isoformat() if self.created_at else None,
            "updated_at":       self.updated_at.isoformat() if self.updated_at else None,
            # Never expose raw keys unless explicitly requested (admin test only)
            "has_key":          bool(self.api_key_encrypted),
            "has_secret":       bool(self.api_secret_encrypted),
            "has_token":        bool(self.access_token),
        }


class UserBrokerCredential(db.Model):
    """Per-user broker API credentials — one row per (user, provider), so a
    single user can connect multiple brokers (Delta + Binance + Zerodha,
    etc.) simultaneously. See app/services/trading/broker_registry.py for
    the full list of supported providers and what fields each needs.
    Deliberately a separate table from APIConfig: APIConfig is shared/
    admin-managed data-feed & platform config, while this table is personal,
    per-user, non-custodial trading credentials — one user's key can never
    be used to place another user's order."""
    __tablename__ = "user_broker_credentials"

    id       = db.Column(db.Integer, primary_key=True)
    user_id  = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    provider = db.Column(db.String(50), nullable=False, default="delta_exchange")

    api_key_encrypted        = db.Column(db.Text)
    api_secret_encrypted     = db.Column(db.Text)
    # Some exchanges (OKX, Bitget, KuCoin) require a third secret — a
    # passphrase set at API-key-creation time, distinct from the account
    # login password. Optional; only used when the broker's auth_type is
    # "api_key_secret_passphrase" (see broker_registry.py).
    passphrase_encrypted     = db.Column(db.Text)

    is_active         = db.Column(db.Boolean, default=True)
    connection_status = db.Column(db.String(20), default="unknown")  # ok, error, unknown
    last_sync         = db.Column(db.DateTime)
    last_latency_ms   = db.Column(db.Integer)
    last_error         = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "provider", name="uq_user_broker_provider"),)

    def set_api_key(self, plaintext: str):
        from app.services.security.crypto import encrypt_value
        self.api_key_encrypted = encrypt_value(plaintext) if plaintext else ""

    def set_api_secret(self, plaintext: str):
        from app.services.security.crypto import encrypt_value
        self.api_secret_encrypted = encrypt_value(plaintext) if plaintext else ""

    def set_passphrase(self, plaintext: str):
        from app.services.security.crypto import encrypt_value
        self.passphrase_encrypted = encrypt_value(plaintext) if plaintext else ""

    def get_api_key(self) -> str | None:
        from app.services.security.crypto import decrypt_value, is_encrypted
        if not self.api_key_encrypted:
            return None
        if not is_encrypted(self.api_key_encrypted):
            return self.api_key_encrypted
        return decrypt_value(self.api_key_encrypted)

    def get_api_secret(self) -> str | None:
        from app.services.security.crypto import decrypt_value, is_encrypted
        if not self.api_secret_encrypted:
            return None
        if not is_encrypted(self.api_secret_encrypted):
            return self.api_secret_encrypted
        return decrypt_value(self.api_secret_encrypted)

    def get_passphrase(self) -> str | None:
        from app.services.security.crypto import decrypt_value, is_encrypted
        if not self.passphrase_encrypted:
            return None
        if not is_encrypted(self.passphrase_encrypted):
            return self.passphrase_encrypted
        return decrypt_value(self.passphrase_encrypted)

    def to_dict(self):
        from app.services.trading.broker_registry import get_broker
        meta = get_broker(self.provider) or {}
        return {
            "id":                self.id,
            "provider":          self.provider,
            "provider_label":    meta.get("label", self.provider),
            "category":          meta.get("category"),
            "trading_enabled":   meta.get("trading_enabled", False),
            "is_active":         self.is_active,
            "connection_status": self.connection_status,
            "last_sync":         self.last_sync.isoformat() if self.last_sync else None,
            "last_latency_ms":   self.last_latency_ms,
            "last_error":        self.last_error,
            "has_key":           bool(self.api_key_encrypted),
            "has_secret":        bool(self.api_secret_encrypted),
            "has_passphrase":    bool(self.passphrase_encrypted),
            "created_at":        self.created_at.isoformat() if self.created_at else None,
        }


class APILog(db.Model):
    __tablename__ = "api_logs"

    id              = db.Column(db.Integer, primary_key=True)
    api_config_id   = db.Column(db.Integer, db.ForeignKey("api_configs.id"), nullable=False)
    action          = db.Column(db.String(100))   # test, fetch, auth, etc.
    status          = db.Column(db.String(20))    # ok, error
    response_time_ms= db.Column(db.Integer)
    error_message   = db.Column(db.Text)
    details         = db.Column(db.JSON, default=dict)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id":               self.id,
            "api_config_id":    self.api_config_id,
            "action":           self.action,
            "status":           self.status,
            "response_time_ms": self.response_time_ms,
            "error_message":    self.error_message,
            "details":          self.details,
            "created_at":       self.created_at.isoformat(),
        }
