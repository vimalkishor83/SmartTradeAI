"""Regression coverage for Delta algo execution guardrails."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.trading.algo_policy import preview_order, validate_policy_payload


def test_policy_requires_both_positive_limits_and_preserves_order_rules():
    policy = validate_policy_payload({
        "max_margin_amount": "2000",
        "max_notional_amount": "10000",
        "max_leverage": 5,
        "order_rules": {"buy_entry": {"order_type": "market_order", "time_in_force": None}},
    })

    assert policy["mode"] == "paper"
    assert policy["enabled"] is False
    assert policy["order_rules"]["buy_entry"]["order_type"] == "market_order"
    assert policy["order_rules"]["sell_entry"]["order_type"] == "limit_order"


def test_policy_rejects_invalid_leverage_and_order_type():
    with pytest.raises(ValueError, match="max_leverage"):
        validate_policy_payload({"max_margin_amount": 1, "max_notional_amount": 1, "max_leverage": 101})
    with pytest.raises(ValueError, match="order_type"):
        validate_policy_payload({"max_margin_amount": 1, "max_notional_amount": 1, "order_rules": {"buy_entry": {"order_type": "stop"}}})


def test_preview_applies_the_stricter_margin_or_notional_cap():
    policy = SimpleNamespace(max_margin_amount=Decimal("2000"), max_notional_amount=Decimal("10000"), max_leverage=5)
    result = preview_order(policy, price="100", requested_size=200, leverage=5)

    assert result["allowed_size"] == 100
    assert result["notional_amount"] == 10000.0
    assert result["margin_amount"] == 2000.0
    assert result["limited_by"] == "both"


def test_preview_rejects_leverage_above_policy():
    policy = SimpleNamespace(max_margin_amount=Decimal("2000"), max_notional_amount=Decimal("10000"), max_leverage=3)
    with pytest.raises(ValueError, match="exceeds"):
        preview_order(policy, price=100, requested_size=1, leverage=4)
