"""Centralized environment safety gates for high-impact integrations."""

from flask import current_app, has_app_context


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}


def as_bool(value, default=False):
    """Parse boolean configuration values without truthiness surprises."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return default


def feature_enabled(name):
    """Read a typed feature flag, failing closed when absent or invalid."""
    if not has_app_context():
        return False
    return as_bool(current_app.config.get(name), False)


def broker_trading_enabled():
    return feature_enabled("BROKER_TRADING_ENABLED")


def protective_orders_enabled():
    return feature_enabled("PROTECTIVE_ORDERS_ENABLED")


def telegram_notifications_enabled():
    return feature_enabled("TELEGRAM_NOTIFICATIONS_ENABLED")


def migrations_on_startup():
    return feature_enabled("RUN_MIGRATIONS_ON_STARTUP")


def safety_disabled_payload(feature):
    messages = {
        "broker_trading": (
            "broker_trading_disabled",
            "Broker trading is disabled in this environment; no live order was sent.",
        ),
        "protective_orders": (
            "protective_orders_disabled",
            "Protective-order execution is disabled in this environment.",
        ),
        "telegram": (
            "telegram_disabled",
            "Telegram notifications are disabled in this environment; nothing was sent.",
        ),
    }
    code, message = messages[feature]
    return {"error": message, "code": code, "blocked": True}
