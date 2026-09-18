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


def broker_connections_enabled():
    return feature_enabled("BROKER_CONNECTIONS_ENABLED")


def protective_orders_enabled():
    return feature_enabled("PROTECTIVE_ORDERS_ENABLED")


def telegram_notifications_enabled():
    return feature_enabled("TELEGRAM_NOTIFICATIONS_ENABLED")


def telegram_delivery_mode():
    """Return the explicit Telegram routing policy, failing closed otherwise."""
    if not has_app_context():
        return "disabled"
    mode = str(current_app.config.get("TELEGRAM_DELIVERY_MODE", "disabled")).strip().lower()
    supported = {"group_only", "news_group_individual_signals"}
    return mode if mode in supported else "disabled"


def telegram_group_delivery_enabled():
    """Whether the configured shared group may receive news updates."""
    return telegram_notifications_enabled() and telegram_delivery_mode() in {
        "group_only", "news_group_individual_signals",
    }


def telegram_individual_delivery_enabled():
    """Whether opted-in users may receive personal Telegram alerts."""
    return (
        telegram_notifications_enabled()
        and telegram_delivery_mode() == "news_group_individual_signals"
    )


def migrations_on_startup():
    return feature_enabled("RUN_MIGRATIONS_ON_STARTUP")


def trading_execution_mode():
    """Return the explicit execution mode, failing closed outside a request."""
    if not has_app_context():
        return "disabled"
    mode = str(current_app.config.get("TRADING_EXECUTION_MODE", "disabled")).strip().lower()
    return mode if mode in {"live", "paper"} else "disabled"


def paper_trading_enabled():
    """Paper mode is explicit and must be enabled separately from live trading."""
    return trading_execution_mode() == "paper" and feature_enabled("PAPER_TRADING_ENABLED")


def safety_disabled_payload(feature):
    messages = {
        "broker_trading": (
            "broker_trading_disabled",
            "Broker trading is disabled in this environment; no live order was sent.",
        ),
        "broker_connections": (
            "broker_connections_disabled",
            "Broker connections are disabled in this environment; no credentials were stored or tested.",
        ),
        "protective_orders": (
            "protective_orders_disabled",
            "Protective-order execution is disabled in this environment.",
        ),
        "telegram": (
            "telegram_disabled",
            "Telegram notifications are disabled in this environment; nothing was sent.",
        ),
        "telegram_individual": (
            "telegram_individual_disabled",
            "Individual Telegram delivery is disabled in this environment; no personal message was sent.",
        ),
    }
    code, message = messages[feature]
    return {"error": message, "code": code, "blocked": True}
