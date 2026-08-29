import logging
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

    # "threading" suits the Werkzeug dev server (run.py). wsgi.py sets
    # SOCKETIO_ASYNC_MODE=eventlet before create_app() so the gunicorn
    # eventlet-worker path actually uses the eventlet transport.
    SOCKETIO_ASYNC_MODE = os.environ.get("SOCKETIO_ASYNC_MODE", "threading")

    # Redis pub/sub backing for Socket.IO so emit()/broadcast_ticker() fan out
    # across every worker and replica. Without it, Socket.IO delivery is
    # process-local: a client attached to worker B never sees an event emitted
    # from worker A, and it fails silently (stale prices) rather than erroring.
    # Falls back to REDIS_URL; empty means single-process mode.
    SOCKETIO_MESSAGE_QUEUE = os.environ.get("SOCKETIO_MESSAGE_QUEUE") or os.environ.get("REDIS_URL", "")

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

    # Note: the canonical timeframe list is now admin-managed via
    # PlatformConfig (app/models/platform_config.py) rather than a static
    # config constant.

    # Pagination
    ITEMS_PER_PAGE = 20


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///smarttrade_dev.db"
    )
    # Use Redis if REDIS_URL is set and reachable; otherwise fall back to in-memory
    CACHE_TYPE = "RedisCache" if os.environ.get("REDIS_URL") else "SimpleCache"
    # Cache parsed Jinja templates even in debug. By default Flask ties
    # template auto-reload to DEBUG, so every full-page load re-reads and
    # re-parses the template from disk (some pages are 1000+ lines). We don't
    # edit templates during normal use, so caching them makes page navigations
    # faster. Set TEMPLATES_AUTO_RELOAD=1 in the env only while editing HTML.
    TEMPLATES_AUTO_RELOAD = os.environ.get("TEMPLATES_AUTO_RELOAD", "0") == "1"


_INSECURE_DEFAULTS = {"dev-secret-key-change-in-production", "jwt-secret-change-in-production"}


class ProductionConfig(Config):
    DEBUG = False
    # SQLite is fine here too — DATABASE_URL just needs to point at whatever
    # engine you're running (falls back to the local sqlite file so a first
    # deploy without DATABASE_URL set doesn't hard-crash before you've had a
    # chance to configure it).
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///smarttrade_prod.db")
    CACHE_TYPE = "RedisCache" if os.environ.get("REDIS_URL") else "SimpleCache"
    # Secure by default (cookies require HTTPS) — but a LAN-only deployment
    # behind a plain-HTTP reverse proxy (no TLS cert yet) has nowhere to send
    # a Secure cookie, which would silently break login. Set
    # FORCE_INSECURE_COOKIES=true in that specific case only; never on a
    # deployment reachable from the internet.
    _insecure_cookies_ok = os.environ.get("FORCE_INSECURE_COOKIES", "false").lower() == "true"
    JWT_COOKIE_SECURE = not _insecure_cookies_ok
    JWT_COOKIE_CSRF_PROTECT = True
    SESSION_COOKIE_SECURE = not _insecure_cookies_ok


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

    # The two checks below are WARNINGS, not hard failures. Both describe
    # configurations that are genuinely wrong for a multi-instance enterprise
    # deployment but perfectly serviceable for the single-process LAN/IIS
    # deployment this app also supports — hard-failing would brick those.
    # The dangerous half of the CORS case is already neutralised structurally
    # in _init_extensions(), which refuses to enable credentialed CORS
    # alongside a wildcard origin regardless of what is configured here.
    if cfg is ProductionConfig:
        _log = logging.getLogger(__name__)

        # Flask-CORS reflects the caller's own Origin back when origins="*"
        # and credentials are enabled, which would let any site make
        # authenticated /api/* calls for a logged-in user. _init_extensions
        # drops credentials support in that case, so the exploit is closed —
        # but a wildcard is still not what you want in production.
        if "*" in cfg.CORS_ORIGINS:
            _log.warning(
                "CORS_ORIGINS='*' in production — credentialed CORS has been DISABLED "
                "to keep this safe, which will break browser clients on another origin "
                "that rely on cookies. Set an explicit allowlist, e.g. "
                "CORS_ORIGINS=https://app.example.com,https://www.example.com"
            )

        # In-memory limiter state is per-process: it resets on restart and is
        # not shared across workers/replicas, so configured limits stop being
        # global the moment more than one process exists — brute-force
        # protection silently becomes N times weaker.
        if str(cfg.RATELIMIT_STORAGE_URI).startswith("memory://"):
            _log.warning(
                "Rate limiter is using in-memory storage in production — limits are "
                "per-process and reset on restart, so they are NOT enforced globally "
                "across gunicorn workers or replicas. Set REDIS_URL to fix."
            )

        # A real deployment already made exactly this mistake once: FLASK_ENV
        # was set to production while DATABASE_URL still pointed at the same
        # SQLite file the dev server writes to (see deploy/SCALING.md's
        # environments audit) — every dev restart and every production
        # request landing in the same file, with no schema/data separation.
        # Name-matched, not path-matched, since dev's own default filename is
        # exactly what a copy-pasted .env would still contain.
        db_uri = str(cfg.SQLALCHEMY_DATABASE_URI)
        if "sqlite" in db_uri and "_dev.db" in db_uri:
            _log.warning(
                f"DATABASE_URL in production looks like the development SQLite file "
                f"({db_uri}) — production and dev would read/write the exact same "
                f"database. Point DATABASE_URL at a dedicated production database "
                f"(Postgres is already supported — see .env.example and deploy/SCALING.md)."
            )
    return cfg
