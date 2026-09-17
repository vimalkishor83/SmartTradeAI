"""Regression tests for development safety and shared data contracts."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch


def _approved_headers(app):
    from flask_jwt_extended import create_access_token
    from app.extensions import db
    from app.models.user import Role, User

    with app.app_context():
        role = Role.query.filter_by(name="free").first()
        user = User(
            username="contract-user",
            email="contract-user@example.com",
            role_id=role.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}, user.id


def test_development_profile_is_paper_and_fail_closed():
    from app.config import DevelopmentConfig

    assert DevelopmentConfig.DEBUG is False
    assert DevelopmentConfig.BROKER_TRADING_ENABLED is False
    assert DevelopmentConfig.BROKER_CONNECTIONS_ENABLED is False
    assert DevelopmentConfig.PROTECTIVE_ORDERS_ENABLED is False
    assert DevelopmentConfig.TELEGRAM_NOTIFICATIONS_ENABLED is False
    assert DevelopmentConfig.RUN_MIGRATIONS_ON_STARTUP is False
    assert DevelopmentConfig.TRADING_EXECUTION_MODE == "paper"
    assert DevelopmentConfig.PAPER_TRADING_ENABLED is True


def test_market_health_contract_is_sanitized_and_has_freshness(client):
    response = client.get("/api/v1/system/market-health")

    assert response.status_code == 200
    body = response.get_json()
    assert body["_meta"]["contract_version"] == "1.0"
    assert body["_meta"]["source"] == "provider_verification"
    assert body["freshness"]["state"] in {"ready", "degraded", "unavailable"}
    assert "providers" in body
    assert all("api_key" not in provider for provider in body["providers"])


def test_development_paper_order_is_idempotent_and_never_calls_broker(app, client, monkeypatch):
    from app.extensions import db
    from app.models.trading_order import PaperOrder

    headers, _ = _approved_headers(app)
    app.config.update(
        TRADING_EXECUTION_MODE="paper",
        PAPER_TRADING_ENABLED=True,
        BROKER_TRADING_ENABLED=False,
    )
    def fail_if_called(*args, **kwargs):
        raise AssertionError("paper order reached a broker client")

    monkeypatch.setattr("app.api.v1.trading.get_configured_client", fail_if_called)
    payload = {
        "symbol": "BTCUSDT", "side": "buy", "order_type": "limit_order",
        "size": 1, "limit_price": 100,
    }
    first = client.post("/api/v1/trading/orders", headers={**headers, "Idempotency-Key": "paper-1"}, json=payload)
    second = client.post("/api/v1/trading/orders", headers={**headers, "Idempotency-Key": "paper-1"}, json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["idempotent_replay"] is True
    with app.app_context():
        assert PaperOrder.query.count() == 1


def test_protective_close_is_blocked_without_context_or_broker_call():
    from app.tasks.protective_order_tasks import _execute_close

    order = SimpleNamespace(id=901, error_message=None)
    asset = SimpleNamespace(symbol="BTCUSDT")
    with patch("app.services.trading.delta_trading.get_configured_client") as broker:
        assert _execute_close(order, asset, 100.0) is False

    broker.assert_not_called()
    assert "disabled" in order.error_message.lower()


def test_protective_close_is_blocked_inside_context(app):
    from app.tasks.protective_order_tasks import _execute_close

    order = SimpleNamespace(id=902, error_message=None)
    asset = SimpleNamespace(symbol="BTCUSDT")
    app.config["PROTECTIVE_ORDERS_ENABLED"] = False
    with app.app_context():
        with patch("app.services.trading.delta_trading.get_configured_client") as broker:
            assert _execute_close(order, asset, 100.0) is False

    broker.assert_not_called()
    assert "disabled" in order.error_message.lower()


def test_disabled_telegram_direct_delivery_never_calls_http(app):
    from app.tasks.notification_tasks import _send_telegram

    app.config["TELEGRAM_NOTIFICATIONS_ENABLED"] = False
    with app.app_context():
        with patch("requests.post") as post:
            assert _send_telegram(SimpleNamespace(), "blocked") is False

    post.assert_not_called()


def test_risk_limits_can_be_saved_and_exposed_before_order_execution(app, client):
    headers, _ = _approved_headers(app)
    saved = client.put("/api/v1/risk/limits", headers=headers, json={
        "enabled": True, "max_total_exposure": 1000,
    })
    assert saved.status_code == 200
    assert saved.get_json()["max_total_exposure"] == 1000

    loaded = client.get("/api/v1/risk/limits", headers=headers)
    assert loaded.status_code == 200
    assert loaded.get_json()["max_total_exposure"] == 1000


def test_signal_lifecycle_contract_tracks_milestones():
    from app.services.signals.lifecycle import lifecycle_snapshot

    lifecycle = lifecycle_snapshot("active", [
        {"type": "generated", "at": "2026-01-01T00:00:00"},
        {"type": "target1", "at": "2026-01-01T01:00:00", "price": 101},
    ], datetime.utcnow() + timedelta(hours=1))

    assert lifecycle["targets"] == {"t1": True, "t2": False, "t3": False}
    assert lifecycle["stop_loss_hit"] is False
    assert lifecycle["last_event"]["type"] == "target1"
