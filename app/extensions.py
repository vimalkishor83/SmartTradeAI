from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from flask_migrate import Migrate
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler

db = SQLAlchemy()
cors = CORS()


def configure_sqlite_concurrency(app):
    """Reduce 'database is locked' errors under the app's concurrent background
    jobs (collector, prewarm, signal-close, auto-generate all write to one
    SQLite file). Enables WAL journal mode (readers don't block a writer) and a
    5s busy_timeout (a writer waits for the lock instead of erroring instantly).
    No-op for non-SQLite databases."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    import sqlite3

    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not uri.startswith("sqlite"):
        return

    # Register on the Engine class (fires for every SQLite connection in any
    # pool/thread) — avoids needing a live engine or app context at setup time.
    if getattr(configure_sqlite_concurrency, "_registered", False):
        return

    @event.listens_for(Engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):
        if not isinstance(dbapi_conn, sqlite3.Connection):
            return
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")   # ms — wait up to 5s for a lock
        cur.execute("PRAGMA synchronous=NORMAL")  # safe with WAL, much faster
        cur.close()

    configure_sqlite_concurrency._registered = True


bcrypt = Bcrypt()
jwt = JWTManager()
socketio = SocketIO()
limiter = Limiter(key_func=get_remote_address)
cache = Cache()
migrate = Migrate()
scheduler = BackgroundScheduler()
