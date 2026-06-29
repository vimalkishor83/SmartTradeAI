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

    RATELIMIT_DEFAULT = "200 per day;50 per hour"
    RATELIMIT_STORAGE_URL = os.environ.get("REDIS_URL", "memory://")

    SOCKETIO_ASYNC_MODE = "threading"

    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")

    # Email
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "noreply@smarttradeai.com")

    # Telegram
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

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
    CACHE_TYPE = "SimpleCache"


class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    CACHE_TYPE = "RedisCache"
    JWT_COOKIE_SECURE = True
    JWT_COOKIE_CSRF_PROTECT = True


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=5)


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config():
    env = os.environ.get("FLASK_ENV", "development")
    return config_map.get(env, DevelopmentConfig)
