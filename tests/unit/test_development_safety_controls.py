"""Regression coverage for development fail-closed integration controls."""

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask

from app.config import Config, DevelopmentConfig, TestingConfig
from app.services.safety import (
    as_bool,
    feature_enabled,
    protective_orders_enabled,
    telegram_notifications_enabled,
)


def test_safety_flags_default_to_false_and_debug_is_forced_off():
    assert Config.BROKER_TRADING_ENABLED is False
    assert Config.PROTECTIVE_ORDERS_ENABLED is False
    assert Config.TELEGRAM_NOTIFICATIONS_ENABLED is False
    assert Config.RUN_MIGRATIONS_ON_STARTUP is False
    assert DevelopmentConfig.BROKER_TRADING_ENABLED is False
    assert DevelopmentConfig.PROTECTIVE_ORDERS_ENABLED is False
    assert DevelopmentConfig.TELEGRAM_NOTIFICATIONS_ENABLED is False
    assert DevelopmentConfig.RUN_MIGRATIONS_ON_STARTUP is False
    assert DevelopmentConfig.DEBUG is False
    assert DevelopmentConfig.RUN_MIGRATIONS_ON_STARTUP is False
    assert TestingConfig.RUN_MIGRATIONS_ON_STARTUP is True


def test_safety_flag_parser_handles_real_boolean_values():
    assert as_bool(True) is True
    assert as_bool(False) is False
    assert as_bool("1") is True
    assert as_bool("true") is True
    assert as_bool("0") is False
    assert as_bool("false") is False
    assert as_bool("unexpected") is False


def test_manual_mutations_are_guarded_before_external_calls():
    trading = (Path(__file__).parents[2] / "app" / "api" / "v1" / "trading.py").read_text()
    place_start = trading.index("def place_order")
    cancel_start = trading.index("def cancel_order")
    assert trading.index('safety_disabled_payload("broker_trading")', place_start) < trading.index("client.place_order", place_start)
    assert trading.index('safety_disabled_payload("broker_trading")', cancel_start) < trading.index("client.cancel_order", cancel_start)


def test_protective_and_telegram_paths_are_fail_closed():
    root = Path(__file__).parents[2]
    protective_api = (root / "app" / "api" / "v1" / "protective_orders.py").read_text()
    protective_task = (root / "app" / "tasks" / "protective_order_tasks.py").read_text()
    notifications = (root / "app" / "tasks" / "notification_tasks.py").read_text()
    live_read = (root / "app" / "services" / "signals" / "live_read_notifications.py").read_text()
    auth = (root / "app" / "auth" / "routes.py").read_text()
    admin = (root / "app" / "api" / "v1" / "admin.py").read_text()

    create_start = protective_api.index("def create_protective_order")
    update_start = protective_api.index("def update_protective_order")
    assert protective_api.index('safety_disabled_payload("protective_orders")', create_start) < protective_api.index("_positive_level", create_start)
    assert protective_api.index('safety_disabled_payload("protective_orders")', update_start) < protective_api.index("_positive_level", update_start)
    assert protective_task.index("protective_orders_enabled") < protective_task.index("client.place_order")
    assert notifications.index("telegram_notifications_enabled") < notifications.index("requests.post")
    assert live_read.index("telegram_notifications_enabled", live_read.index("def enqueue_live_read_event_notifications")) < live_read.index("Notification", live_read.index("def enqueue_live_read_event_notifications"))
    assert auth.index('safety_disabled_payload("telegram")', auth.index("def find_telegram_chat_id")) < auth.index("requests.get", auth.index("def find_telegram_chat_id"))
    assert auth.index('safety_disabled_payload("telegram")', auth.index("def send_telegram_test")) < auth.index("requests.post", auth.index("def send_telegram_test"))
    assert admin.index('safety_disabled_payload("telegram")', admin.index("def telegram_channel_broadcast")) < admin.index("_send_to_chat", admin.index("def telegram_channel_broadcast"))
    assert admin.index('safety_disabled_payload("telegram")', admin.index("def telegram_security_test")) < admin.index("send_security_alert", admin.index("def telegram_security_test"))


def test_startup_migrations_are_explicitly_gated():
    source = (Path(__file__).parents[2] / "app" / "__init__.py").read_text()
    assert "RUN_MIGRATIONS_ON_STARTUP=0" in source
    assert "migrations_on_startup()" in source


def test_safety_gates_fail_closed_without_application_context():
    assert feature_enabled("PROTECTIVE_ORDERS_ENABLED") is False
    assert protective_orders_enabled() is False
    assert telegram_notifications_enabled() is False


def test_safety_gate_honors_explicit_enabled_value_in_application_context():
    app = Flask(__name__)
    app.config["PROTECTIVE_ORDERS_ENABLED"] = True

    with app.app_context():
        assert protective_orders_enabled() is True


def test_execute_close_is_blocked_without_application_context():
    from app.tasks.protective_order_tasks import _execute_close

    order = SimpleNamespace(id=101, error_message=None)
    asset = SimpleNamespace(symbol="BTCUSDT")

    with patch("app.services.trading.delta_trading.get_configured_client") as broker:
        assert _execute_close(order, asset, 100.0) is False

    broker.assert_not_called()
    assert "disabled" in order.error_message.lower()


def test_execute_close_is_blocked_in_application_context():
    from app.tasks.protective_order_tasks import _execute_close

    app = Flask(__name__)
    app.config["PROTECTIVE_ORDERS_ENABLED"] = False
    order = SimpleNamespace(id=102, error_message=None)
    asset = SimpleNamespace(symbol="BTCUSDT")

    with app.app_context():
        with patch("app.services.trading.delta_trading.get_configured_client") as broker:
            assert _execute_close(order, asset, 100.0) is False

    broker.assert_not_called()
    assert "disabled" in order.error_message.lower()


def test_disabled_telegram_user_delivery_does_not_call_http():
    from app.tasks.notification_tasks import _send_telegram

    app = Flask(__name__)
    app.config["TELEGRAM_NOTIFICATIONS_ENABLED"] = False

    with app.app_context():
        with patch("requests.post") as post:
            assert _send_telegram(SimpleNamespace(), "hello") is False

    post.assert_not_called()


def test_disabled_telegram_queue_skips_claimed_row_without_sending():
    from app.tasks import notification_tasks

    class Column:
        def asc(self):
            return self

        def in_(self, values):
            return self

    class Query:
        def __init__(self, rows):
            self.rows = rows

        def filter_by(self, **filters):
            self.rows = [
                row for row in self.rows
                if all(getattr(row, key) == value for key, value in filters.items())
            ]
            return self

        def order_by(self, *columns):
            return self

        def limit(self, count):
            return self

        def filter(self, expression):
            return self

        def all(self):
            return self.rows

    notification = SimpleNamespace(
        id=7,
        user_id=3,
        channel="telegram",
        created_at=None,
        is_sent=False,
    )
    user = SimpleNamespace(
        id=3,
        email_notifications=False,
        telegram_enabled=True,
        telegram_chat_id="test-chat",
    )

    class FakeNotification:
        id = Column()
        created_at = Column()
        query = Query([notification])

    class FakeUser:
        id = Column()
        query = Query([user])

    fake_db = types.SimpleNamespace(session=Mock())
    notification_module = types.ModuleType("app.models.notification")
    notification_module.Notification = FakeNotification
    user_module = types.ModuleType("app.models.user")
    user_module.User = FakeUser
    extensions_module = types.ModuleType("app.extensions")
    extensions_module.db = fake_db

    app = Flask(__name__)
    app.config["TELEGRAM_NOTIFICATIONS_ENABLED"] = False

    def claim(row):
        row.is_sent = True
        return True

    with patch.dict(
        sys.modules,
        {
            "app.models.notification": notification_module,
            "app.models.user": user_module,
            "app.extensions": extensions_module,
        },
    ):
        with patch.object(notification_tasks, "_claim_notification", side_effect=claim):
            with patch.object(notification_tasks, "_send_telegram") as send:
                notification_tasks.send_pending_notifications(app)

    send.assert_not_called()
    assert notification.is_sent is True
    fake_db.session.commit.assert_called_once()
