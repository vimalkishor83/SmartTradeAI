import json
import logging
import os
import re
import threading
import time
import uuid
from flask import Flask, g, request
from app.config import get_config
from app.extensions import db, bcrypt, jwt, socketio, limiter, cache, migrate, scheduler, cors, mail
from app.extensions import configure_sqlite_concurrency
from flask_compress import Compress

compress = Compress()

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _safe_request_id(value):
    """Keep trusted-looking correlation IDs safe for response headers/logs."""
    if isinstance(value, str) and _REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return uuid.uuid4().hex


def create_app(config_class=None):
    app = Flask(
        __name__,
        template_folder="../frontend/templates",
        static_folder="../frontend/static",
    )

    cfg = config_class or get_config()
    app.config.from_object(cfg)

    # Every supported deployment puts a reverse proxy in front of this app
    # (Docker/gunicorn, or IIS+ARR per deploy/README.md). Without ProxyFix,
    # request.remote_addr is the *proxy's* address for every request, so
    # Flask-Limiter keys all clients to one bucket (rate limits become
    # effectively global rather than per-IP) and every AuditLog row records
    # the proxy IP — making the login/brute-force audit trail useless.
    # TRUSTED_PROXY_COUNT is how many proxies sit in front; only trust as many
    # hops as you actually run, since a client can forge extra
    # X-Forwarded-For entries beyond the ones your own proxies append.
    proxy_hops = int(os.environ.get("TRUSTED_PROXY_COUNT", "1"))
    if proxy_hops > 0:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=proxy_hops,
            x_proto=proxy_hops,
            x_host=proxy_hops,
            x_prefix=proxy_hops,
        )

    _init_error_tracking(app)
    _init_extensions(app)
    configure_sqlite_concurrency(app)
    _register_blueprints(app)
    _init_db(app)
    _configure_logging(app)
    _register_request_observability(app)
    _init_scheduler(app)
    _start_streams(app)
    _register_asset_versioning(app)
    _register_platform_config(app)
    _register_approval_gate(app)
    _register_security_visit_alerts(app)

    return app


# API prefixes a "pending"/"rejected" self-registered user may still call —
# account/profile management and read-only reference data, so they can see
# their own status and fix their profile while waiting on approval. Every
# other /api/v1/* prefix (signals, portfolio, trading, journal, etc.) is
# blocked until an admin approves the account.
_APPROVAL_EXEMPT_PREFIXES = (
    "/api/v1/auth",
    "/api/v1/system",
)


def _register_approval_gate(app):
    @app.before_request
    def _enforce_approval():
        from flask import request, jsonify
        from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity

        path = request.path
        if not path.startswith("/api/v1/") or path.startswith(_APPROVAL_EXEMPT_PREFIXES):
            return None
        if request.method == "OPTIONS":
            return None

        try:
            verify_jwt_in_request(optional=True)
        except Exception:
            return None  # let the route's own auth decorator handle it

        user_id = get_jwt_identity()
        if not user_id:
            return None  # unauthenticated request — route decides (public or 401)

        from app.models.user import User
        user = User.query.get(int(user_id))
        if user and user.approval_status != "approved":
            return jsonify({
                "error": "Account pending approval",
                "approval_status": user.approval_status,
                "message": "Your account is awaiting admin approval before you can access this feature.",
            }), 403
        return None


def _register_security_visit_alerts(app):
    """Opt-in security notification for anonymous page visits — off by
    default (PlatformConfig.telegram_security_notify_anonymous_visits)
    since every visit to a public page is high-volume on a live site,
    unlike the other telegram_security_notify_* events which only fire
    on genuinely occasional activity. Scoped to page routes only (the
    `views` blueprint — /home, /login, /asset/<id>, etc.), never /api or
    /static, and only for requests carrying no valid JWT at all (a
    logged-in visitor browsing the dashboard isn't "anonymous access").
    A short per-IP cooldown (via the same Flask-Caching instance used
    elsewhere, e.g. the Fear & Greed cache) collapses a single visitor's
    burst of page loads into one message instead of one per navigation."""
    @app.before_request
    def _notify_anonymous_visit():
        from flask import request

        if request.blueprint != "views" or request.method != "GET":
            return None
        # These are crawler/infra requests, not a person visiting the
        # product — not worth a security notification even when this is on.
        if request.endpoint in ("views.robots_txt", "views.sitemap_xml"):
            return None

        try:
            from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
            verify_jwt_in_request(optional=True)
            if get_jwt_identity():
                return None  # a logged-in visitor — not anonymous access
        except Exception:
            pass  # treat an unparseable/expired token as anonymous too

        try:
            from app.services.platform_config import get_platform_config
            if not get_platform_config().get("telegram_security_notify_anonymous_visits", False):
                return None

            from app.extensions import cache
            cache_key = f"sec_visit_cooldown:{request.remote_addr}"
            if cache.get(cache_key):
                return None
            cache.set(cache_key, True, timeout=300)  # one alert per IP per 5 minutes

            from datetime import datetime
            from app.tasks.notification_tasks import send_security_alert
            when = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
            send_security_alert(
                f"👀 *ANONYMOUS VISIT*\n\n"
                f"📄 Page: `{request.path}`\n"
                f"🌐 IP: `{request.remote_addr}`\n"
                f"💻 User-Agent: `{request.headers.get('User-Agent', '')[:150]}`\n"
                f"🕐 Time: `{when}`"
            )
        except Exception:
            pass
        return None


def _register_request_observability(app):
    """Attach a safe correlation ID and duration to every HTTP response."""
    @app.before_request
    def _start_request_observability():
        g.request_id = _safe_request_id(request.headers.get("X-Request-ID"))
        g.request_started_at = time.perf_counter()

    @app.after_request
    def _finish_request_observability(response):
        request_id = getattr(g, "request_id", None) or _safe_request_id(None)
        started_at = getattr(g, "request_started_at", None)
        duration_ms = 0.0
        if started_at is not None:
            duration_ms = max((time.perf_counter() - started_at) * 1000, 0.0)

        response.headers["X-Request-ID"] = request_id
        if request.endpoint == "static":
            return response

        # JSON keeps user-controlled paths safely escaped while giving log
        # shippers stable fields without changing the existing formatter.
        app.logger.info(
            "request_complete %s",
            json.dumps({
                "request_id": request_id,
                "method": request.method,
                "path": request.path,
                "endpoint": request.endpoint or "",
                "status": response.status_code,
                "duration_ms": round(duration_ms, 2),
            }, separators=(",", ":"), sort_keys=True),
        )
        return response


def _register_asset_versioning(app):
    """Cache-busting for static assets: {{ asset_version('css/main.css') }} appends
    the file's mtime as a ?v= query param, so browsers auto-fetch fresh CSS/JS on
    every deploy instead of serving a stale cached copy indefinitely."""
    @app.context_processor
    def _inject_asset_version():
        def asset_version(rel_path):
            full_path = os.path.join(app.static_folder, rel_path)
            try:
                return str(int(os.path.getmtime(full_path)))
            except OSError:
                return "1"
        return {"asset_version": asset_version}


def _register_platform_config(app):
    """Injects `disabled_nav_items` and `display_timeframes` into every
    template that extends base.html — nav visibility and the canonical
    admin-managed timeframe list, both read through the cache-backed
    get_platform_config()/get_display_timeframes() helpers (same cost class
    as asset_version() above), so pages like Terminal that render their
    timeframe row as static HTML at request time don't need their own
    per-view DB/cache lookup."""
    @app.context_processor
    def _inject_platform_config():
        from app.services.platform_config import (
            get_platform_config, get_display_timeframes, get_terminal_default_timeframe,
        )
        cfg = get_platform_config()
        return {
            "disabled_nav_items": set(cfg.get("disabled_nav_items") or []),
            "display_timeframes": get_display_timeframes(),
            "terminal_default_timeframe": get_terminal_default_timeframe(),
        }


def _init_error_tracking(app):
    """Sentry — genuinely no-op unless SENTRY_DSN is set in the environment.
    This app has zero error-tracking/APM anywhere (only DB-backed
    SystemLog/AuditLog + stdlib logging), so a silent failure in a
    background job (order placement, protective-order monitor, prewarm
    jobs) or a crashed request handler previously had no alerting path at
    all beyond someone noticing a log line after the fact. Wired in behind
    an env-var gate rather than requiring a real Sentry account/DSN to be
    fabricated for this to compile/run -- ready to activate the moment a
    real DSN is configured, doesn't change behavior at all until then.
    """
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=dsn,
            integrations=[FlaskIntegration(), SqlalchemyIntegration()],
            environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            send_default_pii=False,
        )
        logging.getLogger(__name__).info("Sentry error tracking initialized")
    except Exception as e:
        logging.getLogger(__name__).warning(f"Sentry init failed (continuing without it): {e}")


def _init_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    jwt.init_app(app)

    @jwt.token_in_blocklist_loader
    def _check_session_revoked(jwt_header, jwt_payload):
        """Backs admin-configurable session timeout and immediate logout:
        flask-jwt-extended tokens are otherwise stateless JWTs that stay
        valid until their own baked-in expiry no matter what /logout does
        client-side. Every access/refresh token minted since this feature
        shipped carries a "sid" claim pointing at its UserSession row
        (app/models/user_session.py); this runs on every @jwt_required
        request and treats the token as revoked the moment that row is
        revoked or past its (admin-configured) expires_at, even if the
        token itself has not technically expired yet.

        sid is None for tokens minted before this existed, and for the
        short-lived 2FA "partial_token" (which never gets a sid at all) —
        both fall through as "not revoked" rather than breaking on
        upgrade or mid-2FA-flow.
        """
        sid = jwt_payload.get("sid")
        if sid is None:
            return False
        try:
            from datetime import datetime
            from app.models.user_session import UserSession
            session_row = UserSession.query.get(sid)
            if not session_row:
                return True
            if session_row.revoked_at is not None:
                return True
            return session_row.expires_at <= datetime.utcnow()
        except Exception as e:
            logging.getLogger(__name__).error(f"Session blocklist check failed, allowing request: {e}")
            return False
    cors_origins = app.config.get("CORS_ORIGINS", ["*"])
    # supports_credentials is only safe against an explicit origin allowlist.
    # With origins="*" Flask-CORS reflects the caller's own Origin header back,
    # which would let any site issue credentialed /api/* calls for a logged-in
    # user. get_config() hard-refuses that combination in production; here we
    # additionally drop credentials support whenever the list is a wildcard so
    # a dev/LAN config can't accidentally become the permissive-and-credentialed
    # case either.
    cors_wildcard = "*" in cors_origins
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": cors_origins}},
        supports_credentials=not cors_wildcard,
    )
    # "threading" async mode (Werkzeug dev server) does not fully implement
    # the WebSocket frame protocol — expect a benign "Invalid frame header"
    # in the browser console during local dev; the Socket.IO client falls
    # back to long-polling automatically (see the `transports` list in
    # app.js's `io(...)` call) so this doesn't break anything. Production
    # (wsgi.py, gunicorn --worker-class eventlet) uses real eventlet-backed
    # WebSockets instead — see wsgi.py's own comment for why dev deliberately
    # does NOT do the same (eventlet monkey-patching risk on the dev server).
    # async_mode was hardcoded to "threading" while the Dockerfile serves this
    # under gunicorn's *eventlet* worker — an implicit coupling that made the
    # comment above (claiming production gets "real eventlet-backed WebSockets")
    # untrue: threading mode never takes the eventlet transport path. Derive it
    # from config instead, defaulting to the historical "threading" so the dev
    # server is unaffected; wsgi.py sets SOCKETIO_ASYNC_MODE=eventlet for the
    # gunicorn path. message_queue wires cross-process broadcast fan-out —
    # without it an emit() from one worker never reaches clients attached to
    # another (see _start_streams / broadcast_ticker).
    socketio.init_app(
        app,
        cors_allowed_origins=cors_origins,
        async_mode=app.config.get("SOCKETIO_ASYNC_MODE", "threading"),
        message_queue=app.config.get("SOCKETIO_MESSAGE_QUEUE") or None,
    )
    limiter.init_app(app)
    cache.init_app(app)
    mail.init_app(app)
    # TA Summary/MTF Analysis JSON payloads (7 timeframes x dozens of assets,
    # deeply nested) run tens-to-hundreds of KB uncompressed. No reverse
    # proxy in front of gunicorn here does compression, so it wasn't
    # happening anywhere -- gzip cuts this 70-85% for near-zero CPU cost.
    # "text/javascript" matters: Python 3.9+ resolves .js to text/javascript
    # (not application/javascript), so with only the latter listed every JS
    # response — vendor libs plus the page bundles, several hundred KB on a
    # typical page — silently skipped compression entirely.
    app.config.setdefault("COMPRESS_MIMETYPES", [
        "application/json", "text/html", "text/css",
        "application/javascript", "text/javascript",
    ])
    app.config.setdefault("COMPRESS_LEVEL", 6)
    app.config.setdefault("COMPRESS_MIN_SIZE", 500)
    compress.init_app(app)


def _register_blueprints(app):
    from app.auth.routes import auth_bp
    from app.api.v1.signals import signals_bp
    from app.api.v1.assets import assets_bp
    from app.api.v1.market_data import market_data_bp
    from app.api.v1.portfolio import portfolio_bp
    from app.api.v1.watchlist import watchlist_bp
    from app.api.v1.backtesting import backtesting_bp
    from app.api.v1.news import news_bp
    from app.api.v1.scanner import scanner_bp
    from app.api.v1.admin import admin_bp
    from app.api.v1.notifications import notifications_bp
    from app.api.v1.predictions import predictions_bp
    from app.api.v1.risk import risk_bp
    from app.api.v1.journal import journal_bp
    from app.api.v1.trading import trading_bp
    from app.api.v1.protective_orders import protective_orders_bp
    from app.api.v1.comparison import comparison_bp
    from app.api.v1.system import system_bp
    from app.api.v1.geopolitical import geopolitical_bp
    from app.api.v1.forex import forex_bp
    from app.api.v1.sentiment import sentiment_bp
    from app.api.v1.put_call import put_call_bp
    from app.api.v1.dhan import dhan_bp
    from app.api.v1.public_config import public_config_bp
    from app.frontends import frontends_bp
    from app.views import views_bp

    app.register_blueprint(auth_bp, url_prefix="/api/v1/auth")
    app.register_blueprint(signals_bp, url_prefix="/api/v1/signals")
    app.register_blueprint(assets_bp, url_prefix="/api/v1/assets")
    app.register_blueprint(market_data_bp, url_prefix="/api/v1/market-data")
    app.register_blueprint(portfolio_bp, url_prefix="/api/v1/portfolio")
    app.register_blueprint(watchlist_bp, url_prefix="/api/v1/watchlist")
    app.register_blueprint(backtesting_bp, url_prefix="/api/v1/backtesting")
    app.register_blueprint(news_bp, url_prefix="/api/v1/news")
    app.register_blueprint(scanner_bp, url_prefix="/api/v1/scanner")
    app.register_blueprint(admin_bp, url_prefix="/api/v1/admin")
    app.register_blueprint(notifications_bp, url_prefix="/api/v1/notifications")
    app.register_blueprint(predictions_bp, url_prefix="/api/v1/predictions")
    app.register_blueprint(risk_bp, url_prefix="/api/v1/risk")
    app.register_blueprint(journal_bp, url_prefix="/api/v1/journal")
    app.register_blueprint(trading_bp, url_prefix="/api/v1/trading")
    app.register_blueprint(protective_orders_bp, url_prefix="/api/v1/protective-orders")
    app.register_blueprint(comparison_bp, url_prefix="/api/v1/comparison")
    app.register_blueprint(system_bp, url_prefix="/api/v1/system")
    app.register_blueprint(geopolitical_bp, url_prefix="/api/v1/geopolitical-risk")
    app.register_blueprint(forex_bp, url_prefix="/api/v1/forex")
    app.register_blueprint(sentiment_bp, url_prefix="/api/v1/sentiment")
    app.register_blueprint(put_call_bp, url_prefix="/api/v1/put-call-ratio")
    app.register_blueprint(dhan_bp, url_prefix="/api/v1/dhan")
    app.register_blueprint(public_config_bp, url_prefix="/api/v1/public")
    app.register_blueprint(frontends_bp)
    app.register_blueprint(views_bp)


def _init_db(app):
    with app.app_context():
        from app.models.user import UserAssetPreference  # ensure model is registered
        from app.models.journal import JournalEntry       # ensure journal table is created
        from app.models.api_config import UserBrokerCredential  # ensure table is created
        from app.models.platform_config import PlatformConfig  # ensure table is created
        from app.models.live_read_log import LiveReadLog        # ensure table is created

        migrations_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")
        if os.path.isdir(migrations_dir):
            # Flask-Migrate is initialised — run pending Alembic upgrades
            try:
                from flask_migrate import upgrade as _upgrade
                _upgrade(directory=migrations_dir)
            except Exception as e:
                logging.getLogger(__name__).warning(f"flask-migrate upgrade failed, falling back: {e}")
                db.create_all()
                _migrate_columns(app)
        else:
            # No migrations dir yet — create tables + apply ad-hoc column additions
            db.create_all()
            _migrate_columns(app)

        _seed_initial_data(app)


def _migrate_columns(app):
    """Add new columns and indexes to existing tables (SQLite safe — skips if already present)."""
    column_migrations = [
        ("users",      "approval_status",      "TEXT    DEFAULT 'approved'"),
        ("watchlist_items", "alert_set_at_price", "REAL"),
        ("predictions", "entry_price", "REAL"),
        ("user_broker_credentials", "passphrase_encrypted", "TEXT"),
        ("watchlists",      "updated_at", "DATETIME"),
        ("watchlist_items", "updated_at", "DATETIME"),
        ("portfolios",      "updated_at", "DATETIME"),
        ("portfolio_items", "updated_at", "DATETIME"),
        ("users",      "account_size",         "REAL    DEFAULT 100000.0"),
        ("users",      "risk_per_trade_pct",   "REAL    DEFAULT 1.0"),
        ("users",      "min_confidence_filter","INTEGER DEFAULT 60"),
        ("backtests",  "sortino_ratio",        "REAL    DEFAULT 0"),
        ("backtests",  "avg_bars_held",        "REAL    DEFAULT 0"),
        ("backtests",  "total_commission",     "REAL    DEFAULT 0"),
        ("backtests",  "total_slippage",       "REAL    DEFAULT 0"),
        ("backtests",  "commission_pct",       "REAL    DEFAULT 0.1"),
        ("backtests",  "slippage_pct",         "REAL    DEFAULT 0.05"),
        ("backtests",  "exit_reasons",         "TEXT    DEFAULT '{}'"),
        # 2FA columns
        ("users",      "totp_secret",          "TEXT"),
        ("users",      "totp_enabled",         "INTEGER DEFAULT 0"),
        ("users",      "totp_backup_codes",    "TEXT"),
        # Web Push
        ("users",      "push_subscription",    "TEXT"),
        # APIConfig new columns
        ("api_configs","access_token",         "TEXT"),
        ("api_configs","refresh_token",        "TEXT"),
        ("api_configs","websocket_url",        "TEXT"),
        ("api_configs","auth_type",            "TEXT    DEFAULT 'api_key'"),
        ("api_configs","is_default",           "INTEGER DEFAULT 0"),
        ("api_configs","status",               "TEXT    DEFAULT 'active'"),
        ("api_configs","connection_status",    "TEXT    DEFAULT 'unknown'"),
        ("api_configs","priority",             "INTEGER DEFAULT 0"),
        ("api_configs","refresh_interval",     "INTEGER DEFAULT 60"),
        ("api_configs","last_sync",            "DATETIME"),
        ("api_configs","last_latency_ms",      "INTEGER"),
        ("live_read_logs", "data_quality",     "TEXT"),
        ("live_read_logs", "expires_at",        "DATETIME"),
    ]
    index_migrations = [
        # table, index name, columns (raw SQL fragment)
        ("signals",        "idx_signals_status_time",   "status, generated_at"),
        ("signals",        "idx_signals_asset_tf_time", "asset_id, timeframe, generated_at"),
        ("signal_history", "idx_sh_asset_outcome",      "asset_id, outcome"),
        ("signal_history", "idx_sh_closed_at",          "closed_at"),
        ("signal_history", "idx_sh_timeframe_out",      "timeframe, outcome"),
        ("notifications",  "idx_notif_user_sent",       "user_id, is_sent"),
        ("notifications",  "idx_notif_user_read",       "user_id, is_read"),
        ("notifications",  "idx_notif_created",         "created_at"),
        ("audit_logs",     "idx_audit_logs_created",    "created_at"),
        ("system_logs",    "idx_sys_logs_level_time",   "level, created_at"),
        ("journal_entries","idx_journal_user_date",     "user_id, trade_date"),
        ("api_logs",       "idx_api_logs_config_time",  "api_config_id, created_at"),
        ("backtests",      "idx_backtests_user_created","user_id, created_at"),
        ("predictions",    "idx_predictions_asset_tf",  "asset_id, timeframe, predicted_at"),
        ("news",           "idx_news_published",        "published_at"),
    ]

    with app.app_context():
        conn = db.engine.raw_connection()
        cur  = conn.cursor()

        for table, column, col_def in column_migrations:
            try:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
                conn.commit()
            except Exception:
                pass  # column already exists

        for table, idx_name, cols in index_migrations:
            try:
                cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({cols})")
                conn.commit()
            except Exception:
                pass  # index already exists or table not yet created

        # Partial unique index: at most one active signal per (asset,
        # timeframe) — closes the duplicate-signal race window in
        # generate_signals_for_timeframe(). Defensively expire any existing
        # duplicates first so the index can actually be created.
        try:
            cur.execute("""
                UPDATE signals SET status = 'expired'
                WHERE status = 'active' AND id NOT IN (
                    SELECT MAX(id) FROM signals WHERE status = 'active'
                    GROUP BY asset_id, timeframe
                )
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_signals_active_asset_tf
                ON signals (asset_id, timeframe)
                WHERE status = 'active'
            """)
            conn.commit()
        except Exception:
            pass  # index already exists or table not yet created

        # Backfill NULL values in new api_configs columns for existing rows
        try:
            cur.execute("UPDATE api_configs SET status='active' WHERE status IS NULL")
            cur.execute("UPDATE api_configs SET connection_status='unknown' WHERE connection_status IS NULL")
            cur.execute("UPDATE api_configs SET auth_type='api_key' WHERE auth_type IS NULL")
            cur.execute("UPDATE api_configs SET is_default=0 WHERE is_default IS NULL")
            cur.execute("UPDATE api_configs SET priority=0 WHERE priority IS NULL")
            cur.execute("UPDATE api_configs SET refresh_interval=60 WHERE refresh_interval IS NULL")
            conn.commit()
        except Exception:
            pass

        # Drop OHLCV and indicator tables — data is served from the API cache,
        # not stored in the DB.  We drop them here once (safe — they are never
        # written to in the current code, only legacy schema).
        for dead_table in ("market_data", "technical_indicators"):
            try:
                cur.execute(f"DROP TABLE IF EXISTS {dead_table}")
                conn.commit()
            except Exception:
                pass

        conn.close()


def _seed_initial_data(app):
    from app.models.user import Role, Subscription, User, ReferralCode, Broker
    from app.models.asset import Asset

    # Roles — tier ladder is free(0) < basic(1) < premium(2) < pro(3), with
    # admin sitting above the paid ladder entirely (see Subscription.tier_level).
    if not Role.query.first():
        roles = [
            Role(name="admin", description="Full system access", permissions={"all": True}),
            Role(name="pro", description="Pro subscriber", permissions={"signals": True, "ai": True, "backtest": True, "pro_tools": True}),
            Role(name="premium", description="Premium subscriber", permissions={"signals": True, "ai": True, "backtest": True}),
            Role(name="basic", description="Basic subscriber", permissions={"signals": True}),
            Role(name="free", description="Free tier user", permissions={"signals": "delayed"}),
        ]
        db.session.add_all(roles)

    # Subscriptions
    if not Subscription.query.first():
        subs = [
            Subscription(name="free", tier_level=0, price=0, signal_delay_minutes=30, max_watchlist=5, max_alerts=3),
            Subscription(name="basic", tier_level=1, price=299, signal_delay_minutes=5, max_watchlist=15, max_alerts=10),
            Subscription(name="premium", tier_level=2, price=999, signal_delay_minutes=0, max_watchlist=50, max_alerts=50,
                         backtesting_enabled=True, ai_enabled=True,
                         advanced_charts_enabled=True, broker_connect_enabled=True),
            Subscription(name="pro", tier_level=3, price=2499, signal_delay_minutes=0, max_watchlist=200, max_alerts=200,
                         backtesting_enabled=True, ai_enabled=True,
                         advanced_charts_enabled=True, broker_connect_enabled=True),
            Subscription(name="admin", tier_level=99, price=0, signal_delay_minutes=0, max_watchlist=999, max_alerts=999,
                         backtesting_enabled=True, ai_enabled=True,
                         advanced_charts_enabled=True, broker_connect_enabled=True),
        ]
        db.session.add_all(subs)
        db.session.flush()

    # Brokers — admin-manageable dropdown shown on registration (see
    # app/api/v1/admin.py for the CRUD endpoints Admin Panel uses to add
    # more). referral_link is an optional account-opening/affiliate URL
    # shown to users who don't have an account with that broker yet.
    if not Broker.query.first():
        db.session.add_all([
            Broker(name="Zerodha", referral_link="https://zerodha.com/open-account", sort_order=1),
            Broker(name="Upstox", referral_link="https://upstox.com/open-account", sort_order=2),
            Broker(name="Angel One", referral_link="https://www.angelone.in/open-demat-account", sort_order=3),
            Broker(name="Groww", referral_link="https://groww.in/open-demat-account", sort_order=4),
        ])

    # Referral / partner-broker codes — a valid code grants premium instead
    # of the free tier on signup (see app/auth/routes.py:register).
    if not ReferralCode.query.first():
        premium_role = Role.query.filter_by(name="premium").first()
        premium_sub = Subscription.query.filter_by(name="premium").first()
        if premium_role and premium_sub:
            db.session.add_all([
                ReferralCode(
                    code="ZERODHA2026",
                    broker_name="Zerodha",
                    description="Zerodha partner referral — free premium access",
                    referred_role_id=premium_role.id,
                    referred_subscription_id=premium_sub.id,
                ),
                ReferralCode(
                    code="UPSTOX2026",
                    broker_name="Upstox",
                    description="Upstox partner referral — free premium access",
                    referred_role_id=premium_role.id,
                    referred_subscription_id=premium_sub.id,
                ),
            ])

    # Admin user
    #
    # The seeded password comes from SEED_ADMIN_PASSWORD. It used to be the
    # hardcoded literal "Admin@123", seeded unconditionally in EVERY
    # environment — that is a published credential (it is printed on the login
    # page as the demo account), so any production deployment built from this
    # repo shipped with a known-good admin login. Dev/test keep that same
    # default so the demo flow and the existing test fixtures still work
    # unchanged; production must set a real value or the seed refuses to
    # create the account at all (see the raise below) rather than silently
    # installing a backdoor.
    admin_role = Role.query.filter_by(name="admin").first()
    admin_sub = Subscription.query.filter_by(name="admin").first()
    if admin_role and not User.query.filter_by(username="admin").first():
        # Keyed off FLASK_ENV to match get_config()'s own production check —
        # deliberately NOT `not DEBUG`, which is also False under
        # TestingConfig and would break the test suite's seeded fixtures.
        is_production = os.environ.get("FLASK_ENV") == "production" and not app.config.get("TESTING", False)
        seed_password = os.environ.get("SEED_ADMIN_PASSWORD")
        if not seed_password:
            if is_production:
                raise RuntimeError(
                    "Refusing to seed the default admin account in production without "
                    "SEED_ADMIN_PASSWORD. Set SEED_ADMIN_PASSWORD to a real secret before "
                    "first boot, or pre-create the admin user out of band."
                )
            seed_password = "Admin@123"  # dev/demo only — matches the login page's demo hint

        admin = User(
            username="admin",
            email=os.environ.get("SEED_ADMIN_EMAIL", "admin@smarttradeai.com"),
            first_name="Admin",
            last_name="User",
            role_id=admin_role.id,
            subscription_id=admin_sub.id if admin_sub else None,
            is_active=True,
            is_verified=True,
            # The very first admin account is always a super admin — without
            # this, a fresh deployment would seed an admin who can view every
            # admin page but can't actually change anything, with no super
            # admin yet in existence to grant that to them or anyone else.
            is_super_admin=True,
        )
        admin.set_password(seed_password)
        db.session.add(admin)

    # Migrate forex assets from alphavantage → yahoo (yfinance)
    for sym in ["EURUSD","GBPUSD","USDJPY","AUDUSD","USDINR"]:
        a = Asset.query.filter_by(symbol=sym).first()
        if a and a.data_source == "alphavantage":
            a.data_source = "yahoo"

    # Migrate old gold/silver market labels → commodity
    for sym, mkt in [("XAUUSD","gold"),("XAGUSD","silver")]:
        a = Asset.query.filter_by(symbol=sym).first()
        if a and a.market == mkt:
            a.market = "commodity"
            a.data_source = "yahoo"

    # Migrate existing crypto assets from Binance → Delta Exchange India
    for a in Asset.query.filter_by(market="crypto").all():
        if a.data_source == "binance":
            a.data_source = "delta_exchange"
        if a.exchange == "binance":
            a.exchange = "delta_exchange"

    # Add Crude Oil if missing
    if not Asset.query.filter_by(symbol="CLUSD").first():
        db.session.add(Asset(symbol="CLUSD", name="Crude Oil", market="commodity", exchange="commodity", data_source="yahoo"))

    # Assets
    if not Asset.query.first():
        assets = [
            # Crypto
            Asset(symbol="BTCUSDT", name="Bitcoin", market="crypto", exchange="delta_exchange", data_source="delta_exchange"),
            Asset(symbol="ETHUSDT", name="Ethereum", market="crypto", exchange="delta_exchange", data_source="delta_exchange"),
            Asset(symbol="BNBUSDT", name="BNB", market="crypto", exchange="delta_exchange", data_source="delta_exchange"),
            Asset(symbol="SOLUSDT", name="Solana", market="crypto", exchange="delta_exchange", data_source="delta_exchange"),
            Asset(symbol="XRPUSDT", name="XRP", market="crypto", exchange="delta_exchange", data_source="delta_exchange"),
            # Forex
            Asset(symbol="EURUSD", name="Euro/USD", market="forex", exchange="forex", data_source="yahoo"),
            Asset(symbol="GBPUSD", name="GBP/USD", market="forex", exchange="forex", data_source="yahoo"),
            Asset(symbol="USDJPY", name="USD/JPY", market="forex", exchange="forex", data_source="yahoo"),
            Asset(symbol="AUDUSD", name="AUD/USD", market="forex", exchange="forex", data_source="yahoo"),
            Asset(symbol="USDINR", name="USD/INR", market="forex", exchange="forex", data_source="yahoo"),
            # Commodities
            Asset(symbol="XAUUSD", name="Gold",      market="commodity", exchange="commodity", data_source="yahoo"),
            Asset(symbol="XAGUSD", name="Silver",    market="commodity", exchange="commodity", data_source="yahoo"),
            Asset(symbol="CLUSD",  name="Crude Oil", market="commodity", exchange="commodity", data_source="yahoo"),
            # Indian Stocks
            Asset(symbol="RELIANCE", name="Reliance Industries", market="indian_stock", exchange="NSE", data_source="yahoo"),
            Asset(symbol="TCS", name="Tata Consultancy Services", market="indian_stock", exchange="NSE", data_source="yahoo"),
            Asset(symbol="INFY", name="Infosys", market="indian_stock", exchange="NSE", data_source="yahoo"),
            Asset(symbol="HDFCBANK", name="HDFC Bank", market="indian_stock", exchange="NSE", data_source="yahoo"),
            Asset(symbol="ICICIBANK", name="ICICI Bank", market="indian_stock", exchange="NSE", data_source="yahoo"),
            Asset(symbol="SBIN", name="State Bank of India", market="indian_stock", exchange="NSE", data_source="yahoo"),
            # Indices
            Asset(symbol="NIFTY50", name="Nifty 50", market="index", exchange="NSE", data_source="yahoo"),
            Asset(symbol="BANKNIFTY", name="Bank Nifty", market="index", exchange="NSE", data_source="yahoo"),
            Asset(symbol="SENSEX", name="BSE Sensex", market="index", exchange="BSE", data_source="yahoo"),
            Asset(symbol="FINNIFTY", name="Fin Nifty", market="index", exchange="NSE", data_source="yahoo"),
            Asset(symbol="MIDCPNIFTY", name="Midcap Nifty", market="index", exchange="NSE", data_source="yahoo"),
        ]
        db.session.add_all(assets)

    # Backfill risk_reward for old signals that have NULL
    try:
        from app.models.signal import Signal
        null_rr = Signal.query.filter(
            Signal.risk_reward == None,
            Signal.entry_price != None,
            Signal.stop_loss != None,
            Signal.target1 != None,
        ).all()
        for sig in null_rr:
            risk   = abs(sig.entry_price - sig.stop_loss)
            reward = abs(sig.target1 - sig.entry_price)
            if risk > 0:
                sig.risk_reward = round(reward / risk, 2)
    except Exception:
        pass

    # Migrate existing crypto APIConfig from Binance → Delta Exchange India
    from app.models.api_config import APIConfig
    _binance_cfg = APIConfig.query.filter_by(provider="binance", market="crypto").first()
    if _binance_cfg:
        _binance_cfg.name             = "Delta Exchange India (Crypto)"
        _binance_cfg.provider         = "delta_exchange"
        _binance_cfg.base_url         = "https://api.india.delta.exchange"
        _binance_cfg.websocket_url    = "wss://socket.india.delta.exchange"
        _binance_cfg.auth_type        = "none"

    # Seed default API configurations if none exist
    if not APIConfig.query.first():
        defaults = [
            APIConfig(name="Delta Exchange India (Crypto)", provider="delta_exchange", market="crypto",
                      base_url="https://api.india.delta.exchange", websocket_url="wss://socket.india.delta.exchange",
                      auth_type="none", status="active", is_active=True, is_default=True,
                      rate_limit=1200, refresh_interval=45, priority=10),
            APIConfig(name="Yahoo Finance (Forex)", provider="yahoo", market="forex",
                      base_url="https://query1.finance.yahoo.com", auth_type="none",
                      status="active", is_active=True, is_default=True,
                      rate_limit=100, refresh_interval=180, priority=10),
            APIConfig(name="Yahoo Finance (Commodity)", provider="yahoo", market="commodity",
                      base_url="https://query1.finance.yahoo.com", auth_type="none",
                      status="active", is_active=True, is_default=True,
                      rate_limit=100, refresh_interval=180, priority=10),
            APIConfig(name="Yahoo Finance (Indices)", provider="yahoo", market="index",
                      base_url="https://query1.finance.yahoo.com", auth_type="none",
                      status="active", is_active=True, is_default=True,
                      rate_limit=100, refresh_interval=180, priority=10),
            APIConfig(name="Yahoo Finance (Indian Stocks)", provider="yahoo", market="indian_stock",
                      base_url="https://query1.finance.yahoo.com", auth_type="none",
                      status="active", is_active=True, is_default=True,
                      rate_limit=100, refresh_interval=300, priority=10),
        ]
        db.session.add_all(defaults)

    db.session.commit()

    from app.models.platform_config import PlatformConfig
    PlatformConfig.get_singleton()


def run_background_work() -> bool:
    """Whether THIS process should own the scheduler and the market-data stream.

    Historically create_app() started both unconditionally, so every gunicorn
    worker and every replica ran the full job roster and opened its own
    exchange WebSocket. That made `-w 1` load-bearing rather than a tuning
    choice: at `-w 4` you got 4x the outbound API polling (risking upstream
    rate-limit bans), 4x nightly backups/cleanups/retrains, and 4 competing
    copies of every dispatch job.

    RUN_SCHEDULER defaults to "1" so existing single-process deployments
    (docker `-w 1`, serve.py/IIS, run.py) behave exactly as before. To scale
    out: run web replicas with RUN_SCHEDULER=0 and exactly ONE worker process
    with RUN_SCHEDULER=1 (see worker.py).
    """
    return os.environ.get("RUN_SCHEDULER", "1").lower() in ("1", "true", "yes")


def _init_scheduler(app):
    if not run_background_work():
        logging.getLogger(__name__).info(
            "RUN_SCHEDULER=0 — skipping scheduler startup in this process "
            "(expected for web workers when a dedicated worker process owns background jobs)."
        )
        return

    from app.tasks.data_tasks import register_data_jobs
    from app.tasks.notification_tasks import register_notification_jobs
    from app.tasks.protective_order_tasks import register_protective_order_jobs
    from app.services.data.collector import register_collector_job
    from app.services.backup.db_backup import register_backup_job

    with app.app_context():
        register_collector_job(scheduler, app)
        # NOTE: The legacy all-asset signal jobs (register_signal_jobs) are
        # intentionally NOT registered. Signals are generated ONLY from the
        # user's saved Auto-Generate configuration (the `user_auto_generate`
        # job, wired via _resume_auto_generate / the /auto-generate API), so
        # the app never produces signals for assets outside that config.
        register_data_jobs(scheduler, app)
        register_notification_jobs(scheduler, app)
        register_protective_order_jobs(scheduler, app)
        register_backup_job(scheduler, app)

        # Defensively remove any legacy per-timeframe signal jobs left in a
        # persistent jobstore from before this change.
        for tf in ("1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"):
            try:
                scheduler.remove_job(f"signals_{tf}")
            except Exception:
                pass

    if not scheduler.running:
        scheduler.start()

    # Sync the live Auto Generate job against its DB-persisted config now
    # (covers resuming after this process restarts), then keep re-checking
    # on a short interval (covers the split web/worker topology: the web
    # tier runs with RUN_SCHEDULER=0 and never owns this scheduler, so a
    # Start/Stop/Save click made there can only ever reach this process via
    # that persisted row — never as a live signal. Without this poll, a
    # click made after this process's boot had no real effect on the actual
    # running job until this process happened to restart again and catch up,
    # which looked from the admin panel like Auto Generate "randomly stops"
    # and needing Start clicked again every time).
    _sync_auto_generate_from_db(app)
    scheduler.add_job(
        _sync_auto_generate_from_db,
        "interval",
        args=[app],
        id="ag_config_sync",
        seconds=20,
        replace_existing=True,
    )

    # Revert any user whose plan trial (User.trial_expires_at, granted via
    # POST /admin/users/<id>/trial) has run out back to the Free plan. Runs
    # once at boot to catch anything that expired while this process was
    # down, then on a poll — trials are day-granularity so this doesn't need
    # anywhere near the 20s cadence above, just often enough that "N days"
    # is honored close to on time.
    _expire_trials(app)
    scheduler.add_job(
        _expire_trials,
        "interval",
        args=[app],
        id="trial_expiry_check",
        minutes=15,
        replace_existing=True,
    )

    # Housekeeping for user_sessions: nothing ever pruned this table, so a
    # script re-authenticating on every run (a monitor, a bot, a scheduled
    # health-check) leaves one fresh row per login forever — the admin
    # Sessions page was showing dozens of rows for the same user+IP, most
    # already expired. Runs once at boot, then periodically.
    _cleanup_sessions(app)
    scheduler.add_job(
        _cleanup_sessions,
        "interval",
        args=[app],
        id="session_cleanup",
        minutes=30,
        replace_existing=True,
    )

    # Auto pause/resume the Yahoo Finance indian_stock/index API configs
    # around NSE hours (09:00-15:30 IST, Mon-Fri). generate_signals_for_
    # timeframe() already skips indian_stock assets outside these hours on
    # its own, but that's invisible here — this config's `status` field is
    # what the admin API Configs page actually displays, and it was still
    # showing "active" all evening/night/weekend since nothing ever
    # touched it automatically. Runs every 5 minutes so the toggle is
    # never far off the actual open/close time.
    _auto_pause_indian_yahoo_feeds(app)
    scheduler.add_job(
        _auto_pause_indian_yahoo_feeds,
        "interval",
        args=[app],
        id="indian_yahoo_market_hours",
        minutes=5,
        replace_existing=True,
    )


def _expire_trials(app):
    try:
        from datetime import datetime
        with app.app_context():
            from app.models.user import User, Subscription
            from app.models.notification import Notification

            expired = User.query.filter(
                User.trial_expires_at.isnot(None),
                User.trial_expires_at <= datetime.utcnow(),
            ).all()
            if not expired:
                return

            free_sub = Subscription.query.filter_by(name="free").first()
            for user in expired:
                trial_plan = user.subscription.name if user.subscription else "your trial plan"
                if free_sub:
                    user.subscription_id = free_sub.id
                user.trial_expires_at = None
                db.session.add(Notification(
                    user_id=user.id,
                    title="Your trial has ended",
                    message=f"Your {trial_plan} trial has ended — your account is now on the Free plan.",
                    notification_type="trial_ended", channel="web",
                ))
            db.session.commit()
            logging.getLogger(__name__).info(f"Expired {len(expired)} plan trial(s), reverted to Free.")
    except Exception as e:
        logging.getLogger(__name__).warning(f"Trial expiry check failed: {e}")


def _cleanup_sessions(app):
    """Two housekeeping passes over user_sessions, run periodically:

    1. Hard-delete rows that are fully expired — past expires_at, so
       revoked or not, they can never authenticate anything again.
    2. Among whatever's left (still within its expiry window), collapse
       duplicates down to one row per (user_id, ip_address) pair, keeping
       only the most recently active one. A script/monitor that
       re-authenticates on every run otherwise leaves a fresh row each
       time without the previous one having expired yet, which is exactly
       what was cluttering the admin Sessions page.
    """
    try:
        from datetime import datetime
        with app.app_context():
            from app.models.user_session import UserSession
            now = datetime.utcnow()

            expired_count = UserSession.query.filter(UserSession.expires_at <= now).delete(synchronize_session=False)

            remaining = (
                UserSession.query.filter(UserSession.expires_at > now)
                .order_by(UserSession.user_id, UserSession.ip_address, UserSession.last_seen_at.desc())
                .all()
            )
            seen = set()
            stale_ids = []
            for s in remaining:
                key = (s.user_id, s.ip_address)
                if key in seen:
                    stale_ids.append(s.id)
                else:
                    seen.add(key)
            if stale_ids:
                UserSession.query.filter(UserSession.id.in_(stale_ids)).delete(synchronize_session=False)

            db.session.commit()
            if expired_count or stale_ids:
                logging.getLogger(__name__).info(
                    f"Session cleanup: removed {expired_count} expired, {len(stale_ids)} duplicate-IP row(s)."
                )
    except Exception as e:
        db.session.rollback()
        logging.getLogger(__name__).warning(f"Session cleanup failed: {e}")


def _auto_pause_indian_yahoo_feeds(app):
    try:
        from datetime import datetime as _dt, timedelta as _td
        with app.app_context():
            from app.models.api_config import APIConfig
            from app.services.data.fetcher import invalidate_blocked_markets_cache

            ist_now = _dt.utcnow() + _td(hours=5, minutes=30)
            is_open = (
                ist_now.weekday() < 5
                and ist_now.replace(hour=9, minute=0, second=0, microsecond=0) <= ist_now
                <= ist_now.replace(hour=15, minute=30, second=0, microsecond=0)
            )
            desired = "active" if is_open else "paused"

            rows = APIConfig.query.filter(
                APIConfig.provider == "yahoo",
                APIConfig.market.in_(["indian_stock", "index"]),
                APIConfig.status.in_(["active", "paused"]),  # leave an "error" row alone
            ).all()
            changed = [r for r in rows if r.status != desired]
            if not changed:
                return
            for r in changed:
                r.status = desired
            db.session.commit()
            invalidate_blocked_markets_cache()
            logging.getLogger(__name__).info(
                f"Indian Yahoo feeds -> {desired} ({len(changed)} config row(s), IST {ist_now.strftime('%H:%M')})"
            )
    except Exception as e:
        db.session.rollback()
        logging.getLogger(__name__).warning(f"Indian Yahoo market-hours toggle failed: {e}")


_AG_LAST_APPLIED = None  # fingerprint of the config currently armed on the scheduler, or None if stopped


def _sync_auto_generate_from_db(app):
    """Reconciles the live `user_auto_generate` scheduler job against
    AutoGenerateConfig — the single source of truth shared between the web
    tier (writes only, via /auto-generate/start|stop|save) and this worker
    process (the only one that actually runs the job). See the call site
    above for why this needs to run on a poll, not just once at boot."""
    global _AG_LAST_APPLIED
    try:
        from datetime import datetime
        with app.app_context():
            from app.api.v1.signals import _ag_load, _AG_STATE, _AG_JOB_ID, _run_auto_generate, _ag_publish_partial
            saved = _ag_load()

            if not saved or not saved.get("running"):
                if _AG_LAST_APPLIED is not None:
                    try:
                        scheduler.remove_job(_AG_JOB_ID)
                    except Exception:
                        pass
                    _AG_STATE["running"] = False
                    _AG_LAST_APPLIED = None
                    _ag_publish_partial(running=False, next_run_at=None)
                    logging.getLogger(__name__).info("Auto Generate stopped (picked up from saved config).")
                return

            raw_tfs = saved.get("timeframes") or saved.get("timeframe", "1h")
            timeframes = raw_tfs if isinstance(raw_tfs, list) else [raw_tfs]
            fingerprint = (
                tuple(saved.get("asset_ids") or []), tuple(saved.get("markets") or []),
                tuple(timeframes), saved.get("signal_filter", "all"),
                float(saved.get("min_confidence", 0)), int(saved.get("max_per_run", 0)),
                int(saved.get("interval_minutes", 5)), bool(saved.get("telegram_on_signal", True)),
            )
            if fingerprint == _AG_LAST_APPLIED:
                return  # already armed with this exact config — nothing changed since the last poll

            _AG_STATE.update({
                "running":            True,
                "asset_ids":          saved.get("asset_ids", []),
                "markets":            saved.get("markets", []),
                "timeframes":         timeframes,
                "signal_filter":      saved.get("signal_filter", "all"),
                "min_confidence":     float(saved.get("min_confidence", 0)),
                "max_per_run":        int(saved.get("max_per_run", 0)),
                "interval_minutes":   int(saved.get("interval_minutes", 5)),
                "telegram_on_signal": bool(saved.get("telegram_on_signal", True)),
            })
            interval = _AG_STATE["interval_minutes"]
            if interval > 0:
                try:
                    scheduler.remove_job(_AG_JOB_ID)
                except Exception:
                    pass
                scheduler.add_job(
                    _run_auto_generate,
                    "interval",
                    args=[app],
                    id=_AG_JOB_ID,
                    minutes=interval,
                    replace_existing=True,
                    next_run_time=datetime.utcnow(),
                )
            n_assets = len(_AG_STATE["asset_ids"]) or "all"
            logging.getLogger(__name__).info(
                f"Auto Generate (re)armed: {n_assets} assets × {timeframes} every {interval}min"
            )
            _AG_LAST_APPLIED = fingerprint
    except Exception as e:
        logging.getLogger(__name__).warning(f"Auto Generate sync failed: {e}")


class _SystemLogDBHandler(logging.Handler):
    """Mirrors WARNING+ log records into the system_logs table so the Admin
    Panel's System Logs viewer shows real application events instead of
    staying permanently empty (SystemLog was previously only ever defined,
    never written to anywhere in the codebase).

    Runs inside arbitrary logging calls, some of which fire outside a Flask
    app/request context (background scheduler jobs, module import time) —
    everything here is best-effort and swallows its own failures so a
    logging call can never itself crash the app or recurse into more errors.
    """

    _local = threading.local()

    def __init__(self, app):
        super().__init__(level=logging.WARNING)
        self._app = app

    def emit(self, record):
        # A warning/error raised by SQLAlchemy itself while this handler is
        # mid-write (e.g. during db.session.commit()) would otherwise
        # recurse straight back into emit() on the same thread.
        if getattr(self._local, "writing", False):
            return
        if record.name.startswith("sqlalchemy"):
            return
        try:
            self._local.writing = True
            from flask import has_app_context
            from app.extensions import db
            from app.models.audit import SystemLog

            def _write():
                entry = SystemLog(
                    level=record.levelname,
                    module=record.name,
                    message=self.format(record) if self.formatter else record.getMessage(),
                )
                db.session.add(entry)
                db.session.commit()

            if has_app_context():
                _write()
            else:
                with self._app.app_context():
                    _write()
        except Exception:
            # Never let logging itself raise — worst case this event is
            # only in the file log, not the DB-backed admin viewer.
            pass
        finally:
            self._local.writing = False


def _configure_logging(app):
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "app.log")

    # File handler — INFO+ goes to file only. Rotates at midnight UTC and
    # keeps only 1 rotated backup (today's active file + yesterday's),
    # deleting anything older automatically — this file previously grew
    # forever (a plain FileHandler with no cap; caught at ~10MB and
    # climbing on the production VM with no traffic spike to explain it,
    # just normal accumulation) and was the only unbounded-disk-growth
    # source outside the database/Docker's own container logs.
    from logging.handlers import TimedRotatingFileHandler
    file_handler = TimedRotatingFileHandler(log_file, when="midnight", backupCount=1, utc=True)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    # DB handler — WARNING+ only, mirrored into system_logs for the Admin
    # Panel viewer. Kept to a plain "%(message)s" formatter (no timestamp/
    # level prefix) since SystemLog already has its own created_at/level
    # columns for that.
    db_handler = _SystemLogDBHandler(app)
    db_handler.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(db_handler)

    app.logger.setLevel(logging.INFO)

    # Silence noisy third-party loggers
    for name in (
        "werkzeug",
        "apscheduler.executors.default",
        "apscheduler.scheduler",
        "apscheduler.jobstores.default",
        "yfinance",
        "peewee",
        "urllib3",
        "requests",
        "charset_normalizer",
        "socketio",
        "engineio",
        "sqlalchemy",
        "sqlalchemy.engine",
        "sqlalchemy.pool",
    ):
        logging.getLogger(name).setLevel(logging.ERROR)

    # Kill werkzeug request-line output entirely
    logging.getLogger("werkzeug").disabled = True


def _start_streams(app):
    """Start Delta Exchange India WebSocket price stream in background (crypto live prices)."""
    if not run_background_work():
        # One upstream connection per process would multiply exchange
        # connections by the worker count for no benefit — the ingesting
        # process fans ticks out to every other process over the Socket.IO
        # Redis message queue (SOCKETIO_MESSAGE_QUEUE).
        logging.getLogger(__name__).info(
            "RUN_SCHEDULER=0 — skipping Delta market stream in this process."
        )
        return
    try:
        from app.services.data.delta_stream import delta_stream
        delta_stream.start(app)
    except Exception as e:
        logging.getLogger(__name__).warning(f"Delta Exchange stream start failed: {e}")
