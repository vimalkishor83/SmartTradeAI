"""Regression coverage for the real-money trading request boundary."""

from decimal import Decimal

import pytest
import requests

from app.api.v1.trading import _audit_trade, _positive_int, _positive_price
from app.services.trading.delta_trading import DeltaTradingClient, DeltaTradingError


@pytest.mark.parametrize("value", [0, "0", -1, "1.5", True, False, None, float("inf")])
def test_positive_int_rejects_non_positive_or_ambiguous_values(value):
    with pytest.raises(ValueError):
        _positive_int(value, "size", 100)


def test_positive_int_applies_server_side_limit():
    assert _positive_int("12", "size", 100) == 12
    with pytest.raises(ValueError, match="at most"):
        _positive_int("101", "size", 100)


@pytest.mark.parametrize("value", [None, "", "NaN", "Infinity", "-1", "0", True, object()])
def test_positive_price_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        _positive_price(value, "limit_price", required=True)


def test_positive_price_returns_a_finite_decimal_string():
    assert _positive_price(Decimal("12.3400"), "limit_price", required=True) == "12.3400"


def test_get_product_id_converts_provider_errors_to_trading_error(monkeypatch):
    client = DeltaTradingClient(api_key="key", api_secret="secret")

    def fail(*args, **kwargs):
        raise requests.Timeout("provider timed out")

    monkeypatch.setattr("app.services.trading.delta_trading.requests.get", fail)
    with pytest.raises(DeltaTradingError, match="Network error resolving Delta product"):
        client.get_product_id("BTCUSD")


def test_get_product_id_rejects_malformed_provider_payload(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return []

    monkeypatch.setattr("app.services.trading.delta_trading.requests.get", lambda *a, **k: Response())
    client = DeltaTradingClient(api_key="key", api_secret="secret")
    with pytest.raises(DeltaTradingError, match="invalid product response"):
        client.get_product_id("BTCUSD")


def test_client_rejects_non_positive_order_size():
    client = DeltaTradingClient(api_key="key", api_secret="secret")
    with pytest.raises(DeltaTradingError, match="positive whole number"):
        client.place_order(product_id=1, side="buy", size=0, limit_price="1")


def test_trade_audit_records_execution_metadata_without_payload(monkeypatch):
    recorded = {}

    def record(*args, **kwargs):
        recorded["args"] = args
        recorded["kwargs"] = kwargs

    monkeypatch.setattr("app.models.audit.AuditLog.record", record)
    from flask import Flask

    app = Flask(__name__)
    with app.test_request_context("/api/v1/trading/orders", headers={"User-Agent": "test"}):
        _audit_trade(
            7, "order_placed", 123,
            details={"symbol": "BTCUSD", "side": "buy", "size": 2},
        )

    assert recorded["args"][:3] == (7, "order_placed",)
    assert recorded["kwargs"]["resource"] == "trading_order"
    assert recorded["kwargs"]["resource_id"] == "123"
    assert recorded["kwargs"]["details"] == {"symbol": "BTCUSD", "side": "buy", "size": 2}
    assert "api_key" not in recorded["kwargs"]["details"]
    assert "api_secret" not in recorded["kwargs"]["details"]


def test_trade_audit_failure_is_non_blocking(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.models.audit.AuditLog.record", fail)
    from flask import Flask

    app = Flask(__name__)
    with app.test_request_context("/api/v1/trading/orders"):
        _audit_trade(7, "order_cancelled", 123)
