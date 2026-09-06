"""Regression coverage for the real-money trading request boundary."""

from decimal import Decimal

import pytest
import requests

from app.api.v1.trading import _positive_int, _positive_price
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
