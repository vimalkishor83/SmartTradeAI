import logging
import os
from flask import Flask
from app.config import get_config
from app.extensions import db, bcrypt, jwt, socketio, limiter, cache, scheduler


def create_app(config_class=None):
    app = Flask(
        __name__,
        template_folder="../frontend/templates",
        static_folder="../frontend/static",
    )

    cfg = config_class or get_config()
    app.config.from_object(cfg)

    _init_extensions(app)
    _register_blueprints(app)
    _init_db(app)
    _init_scheduler(app)
    _configure_logging(app)

    return app


def _init_extensions(app):
    db.init_app(app)
    bcrypt.init_app(app)
    jwt.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*", async_mode="threading")
    limiter.init_app(app)
    cache.init_app(app)


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
    app.register_blueprint(views_bp)


def _init_db(app):
    with app.app_context():
        from app.models.user import UserAssetPreference  # ensure model is registered
        db.create_all()
        _seed_initial_data(app)


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

    # Add Crude Oil if missing
    if not Asset.query.filter_by(symbol="CLUSD").first():
        db.session.add(Asset(symbol="CLUSD", name="Crude Oil", market="commodity", exchange="commodity", data_source="yahoo"))

    # Assets
    if not Asset.query.first():
        assets = [
            # Crypto
            Asset(symbol="BTCUSDT", name="Bitcoin", market="crypto", exchange="binance", data_source="binance"),
            Asset(symbol="ETHUSDT", name="Ethereum", market="crypto", exchange="binance", data_source="binance"),
            Asset(symbol="BNBUSDT", name="BNB", market="crypto", exchange="binance", data_source="binance"),
            Asset(symbol="SOLUSDT", name="Solana", market="crypto", exchange="binance", data_source="binance"),
            Asset(symbol="XRPUSDT", name="XRP", market="crypto", exchange="binance", data_source="binance"),
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

    db.session.commit()


def _init_scheduler(app):
    from app.tasks.signal_tasks import register_signal_jobs
    from app.tasks.data_tasks import register_data_jobs
    from app.tasks.notification_tasks import register_notification_jobs

    with app.app_context():
        register_signal_jobs(scheduler, app)
        register_data_jobs(scheduler, app)
        register_notification_jobs(scheduler, app)

    if not scheduler.running:
        scheduler.start()


def _configure_logging(app):
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "app.log")

    # File handler — all INFO+ logs go here
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    # Console handler — WARNING+ only (errors you must see)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter(
        "[%(levelname)s] %(name)s: %(message)s"
    ))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    app.logger.setLevel(logging.INFO)

    # Silence noisy third-party loggers even in file
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("peewee").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    print(f"SmartTrade AI - logs -> {log_file}")
