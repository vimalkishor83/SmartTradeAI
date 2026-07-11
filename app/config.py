import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "jwt-secret-change-in-production")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=int(os.environ.get("JWT_ACCESS_EXPIRES_HOURS", 24)))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=int(os.environ.get("JWT_REFRESH_EXPIRES_DAYS", 30)))
    JWT_TOKEN_LOCATION = ["headers", "cookies"]
    JWT_COOKIE_SECURE = False
    JWT_COOKIE_CSRF_PROTECT = True

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_recycle": 300,
        "pool_pre_ping": True,
        "pool_size": 10,
        "max_overflow": 20,
    }

    CACHE_TYPE = os.environ.get("CACHE_TYPE", "SimpleCache")
    CACHE_DEFAULT_TIMEOUT = 300
    CACHE_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    RATELIMIT_DEFAULT = "2000 per day;500 per hour;60 per minute"
    # NOTE: Flask-Limiter reads RATELIMIT_STORAGE_URI (not _URL) — this was
    # previously named _URL, which Flask-Limiter silently ignores, so the
    # limiter was *always* running on in-memory storage even when REDIS_URL
    # was set. In-memory storage means limits reset on every restart and
    # aren't shared across multiple worker processes.
    RATELIMIT_STORAGE_URI = os.environ.get("REDIS_URL", "memory://")

    SOCKETIO_ASYNC_MODE = "threading"

    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")

    # Comma-separated list of allowed browser origins for the REST API and
    # Socket.IO, e.g. "https://app.example.com,https://www.example.com".
    # Defaults to "*" (any origin) which is fine for local/dev use only.
    CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Email
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "noreply@smarttradeai.com")
    # No SMTP credentials configured yet? Suppress actual sending and log the
    # email instead (see app/services/mailer.py) so registration/reset flows
    # keep working end-to-end before you've wired up a real mail provider.
    MAIL_SUPPRESS_SEND = not bool(MAIL_USERNAME and MAIL_PASSWORD)
    FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://127.0.0.1:5000")

    # Telegram
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

    # Web Push (VAPID)
    VAPID_PUBLIC_KEY    = os.environ.get("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY   = os.environ.get("VAPID_PRIVATE_KEY", "")
    VAPID_CLAIMS_EMAIL  = os.environ.get("VAPID_CLAIMS_EMAIL", "mailto:admin@smarttradeai.com")

    # Scheduler
    SCHEDULER_TIMEZONE = "Asia/Kolkata"

    # Signal timeframes
    SIGNAL_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]

    # Pagination
    ITEMS_PER_PAGE = 20


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///smarttrade_dev.db"
    )
    # Use Redis if REDIS_URL is set and reachable; otherwise fall back to in-memory
    CACHE_TYPE = "RedisCache" if os.environ.get("REDIS_URL") else "SimpleCache"


_INSECURE_DEFAULTS = {"dev-secret-key-change-in-production", "jwt-secret-change-in-production"}


class ProductionConfig(Config):
    DEBUG = False
    # SQLite is fine here too — DATABASE_URL just needs to point at whatever
    # engine you're running (falls back to the local sqlite file so a first
    # deploy without DATABASE_URL set doesn't hard-crash before you've had a
    # chance to configure it).
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///smarttrade_prod.db")
    CACHE_TYPE = "RedisCache" if os.environ.get("REDIS_URL") else "SimpleCache"
    JWT_COOKIE_SECURE = True
    JWT_COOKIE_CSRF_PROTECT = True
    SESSION_COOKIE_SECURE = True


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=5)
    # In-memory SQLite uses SQLAlchemy's StaticPool internally, which
    # doesn't accept pool_size/max_overflow (those are QueuePool-only
    # options meant for a real DB server) — Config.SQLALCHEMY_ENGINE_OPTIONS
    # was being inherited unconditionally and crashed create_engine() for
    # any test touching the DB. Only pool_pre_ping (harmless/ignored by
    # StaticPool) carries over; pool_recycle/pool_size/max_overflow don't
    # apply to a per-process in-memory DB anyway.
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config():
    env = os.environ.get("FLASK_ENV", "development")
    cfg = config_map.get(env, DevelopmentConfig)

    # Refuse to boot in production with the placeholder secrets — anyone can
    # forge JWTs/sessions with these known values. Checked here (only when
    # production config is actually selected) rather than at class-definition
    # time, so importing app.config in dev/test never trips this.
    if cfg is ProductionConfig and (
        cfg.SECRET_KEY in _INSECURE_DEFAULTS or cfg.JWT_SECRET_KEY in _INSECURE_DEFAULTS
    ):
        raise RuntimeError(
            "Refusing to start in production with default SECRET_KEY/JWT_SECRET_KEY. "
            "Set real random values via the SECRET_KEY and JWT_SECRET_KEY environment "
            "variables before deploying publicly."
        )
    return cfg
