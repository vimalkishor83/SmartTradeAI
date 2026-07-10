import logging
import os
from flask import Flask
from app.config import get_config
from app.extensions import db, bcrypt, jwt, socketio, limiter, cache, migrate, scheduler, cors, mail
from app.extensions import configure_sqlite_concurrency


def create_app(config_class=None):
    app = Flask(
        __name__,
        template_folder="../frontend/templates",
        static_folder="../frontend/static",
    )

    cfg = config_class or get_config()
    app.config.from_object(cfg)

    _init_extensions(app)
    configure_sqlite_concurrency(app)
    _register_blueprints(app)
    _init_db(app)
    _configure_logging(app)
    _init_scheduler(app)
    _start_streams(app)
    _register_asset_versioning(app)
    _register_approval_gate(app)

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


def _init_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    jwt.init_app(app)
    cors_origins = app.config.get("CORS_ORIGINS", ["*"])
    cors.init_app(app, resources={r"/api/*": {"origins": cors_origins}}, supports_credentials=True)
    socketio.init_app(app, cors_allowed_origins=cors_origins, async_mode="threading")
    limiter.init_app(app)
    cache.init_app(app)
    mail.init_app(app)


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
    from app.api.v1.system import system_bp
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
    app.register_blueprint(system_bp, url_prefix="/api/v1/system")
    app.register_blueprint(frontends_bp)
    app.register_blueprint(views_bp)


def _init_db(app):
    with app.app_context():
        from app.models.user import UserAssetPreference  # ensure model is registered
        from app.models.journal import JournalEntry       # ensure journal table is created
        from app.models.api_config import UserBrokerCredential  # ensure table is created

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
    from app.models.user import Role, Subscription, User
    from app.models.asset import Asset

    # Roles
    if not Role.query.first():
        roles = [
            Role(name="admin", description="Full system access", permissions={"all": True}),
            Role(name="premium", description="Premium subscriber", permissions={"signals": True, "ai": True, "backtest": True}),
            Role(name="free", description="Free tier user", permissions={"signals": "delayed"}),
        ]
        db.session.add_all(roles)

    # Subscriptions
    if not Subscription.query.first():
        subs = [
            Subscription(name="free", price=0, signal_delay_minutes=30, max_watchlist=5, max_alerts=3),
            Subscription(name="premium", price=999, signal_delay_minutes=0, max_watchlist=50, max_alerts=50,
                         backtesting_enabled=True, ai_enabled=True),
            Subscription(name="admin", price=0, signal_delay_minutes=0, max_watchlist=999, max_alerts=999,
                         backtesting_enabled=True, ai_enabled=True),
        ]
        db.session.add_all(subs)
        db.session.flush()

    # Admin user
    admin_role = Role.query.filter_by(name="admin").first()
    admin_sub = Subscription.query.filter_by(name="admin").first()
    if admin_role and not User.query.filter_by(username="admin").first():
        admin = User(
            username="admin",
            email="admin@smarttradeai.com",
            first_name="Admin",
            last_name="User",
            role_id=admin_role.id,
            subscription_id=admin_sub.id if admin_sub else None,
            is_active=True,
            is_verified=True,
        )
        admin.set_password("Admin@123")
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


def _init_scheduler(app):
    from app.tasks.data_tasks import register_data_jobs
    from app.tasks.notification_tasks import register_notification_jobs
    from app.services.data.collector import register_collector_job

    with app.app_context():
        register_collector_job(scheduler, app)
        # NOTE: The legacy all-asset signal jobs (register_signal_jobs) are
        # intentionally NOT registered. Signals are generated ONLY from the
        # user's saved Auto-Generate configuration (the `user_auto_generate`
        # job, wired via _resume_auto_generate / the /auto-generate API), so
        # the app never produces signals for assets outside that config.
        register_data_jobs(scheduler, app)
        register_notification_jobs(scheduler, app)

        # Defensively remove any legacy per-timeframe signal jobs left in a
        # persistent jobstore from before this change.
        for tf in ("1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"):
            try:
                scheduler.remove_job(f"signals_{tf}")
            except Exception:
                pass

    if not scheduler.running:
        scheduler.start()

    # Auto-resume auto-generate if it was running before server restart
    with app.app_context():
        _resume_auto_generate(app)


def _resume_auto_generate(app):
    """If ag_state.json says running=True, re-register the scheduler job."""
    try:
        from app.api.v1.signals import _ag_load, _AG_STATE, _AG_JOB_ID, _run_auto_generate
        saved = _ag_load()
        if not saved or not saved.get("running"):
            return
        # Restore settings into live state
        raw_tfs = saved.get("timeframes") or saved.get("timeframe", "1h")
        timeframes = raw_tfs if isinstance(raw_tfs, list) else [raw_tfs]
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
        from datetime import datetime
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
            f"Auto Generate resumed: {n_assets} assets × {timeframes} every {interval}min"
        )
    except Exception as e:
        logging.getLogger(__name__).warning(f"Auto Generate resume failed: {e}")


def _configure_logging(app):
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "app.log")

    # File handler — INFO+ goes to file only
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(file_handler)

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
    ):
        logging.getLogger(name).setLevel(logging.ERROR)

    # Kill werkzeug request-line output entirely
    logging.getLogger("werkzeug").disabled = True


def _start_streams(app):
    """Start Delta Exchange India WebSocket price stream in background (crypto live prices)."""
    try:
        from app.services.data.delta_stream import delta_stream
        delta_stream.start(app)
    except Exception as e:
        logging.getLogger(__name__).warning(f"Delta Exchange stream start failed: {e}")
