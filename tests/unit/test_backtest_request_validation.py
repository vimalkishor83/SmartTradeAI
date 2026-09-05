"""Contract tests for the shared backtesting request boundary."""
import math

import pytest

from app.services.backtest.validation import (
    parse_asset_id,
    parse_days,
    parse_initial_capital,
    parse_market,
    parse_portfolio_limit,
    parse_strategy_payload,
    parse_timeframe,
)


def test_strategy_payload_normalizes_symbol_and_keeps_valid_defaults():
    result = parse_strategy_payload({"symbol": "  btc-usdt  "})

    assert result == {
        "symbol": "BTC-USDT",
        "timeframe": "1h",
        "initial_capital": 100000.0,
        "strategy": "Default Multi-Indicator",
        "commission": 0.001,
        "slippage": 0.0005,
    }


@pytest.mark.parametrize("payload", [None, [], "payload", {"symbol": ""}])
def test_strategy_payload_rejects_non_object_or_missing_symbol(payload):
    with pytest.raises(ValueError):
        parse_strategy_payload(payload)


@pytest.mark.parametrize("value", ["10h", "1w", 60, ""])
def test_timeframe_must_be_fetchable(value):
    with pytest.raises(ValueError, match="timeframe must be one of"):
        parse_timeframe(value)


@pytest.mark.parametrize("parser", [parse_days, parse_portfolio_limit])
def test_integer_limits_reject_malformed_and_out_of_range_values(parser):
    with pytest.raises(ValueError):
        parser("not-a-number")
    with pytest.raises(ValueError):
        parser(0)


def test_numeric_inputs_reject_non_finite_and_unsafe_values():
    with pytest.raises(ValueError, match="finite"):
        parse_initial_capital(math.inf)
    with pytest.raises(ValueError, match="between"):
        parse_strategy_payload({"symbol": "BTC", "commission": 0.02})
    with pytest.raises(ValueError, match="between"):
        parse_strategy_payload({"symbol": "BTC", "slippage": -0.01})


def test_optional_filters_are_validated_and_normalized():
    assert parse_asset_id("42") == 42
    assert parse_asset_id("") is None
    assert parse_market("crypto") == "crypto"

    with pytest.raises(ValueError, match="asset_id"):
        parse_asset_id("-1")
    with pytest.raises(ValueError, match="market must be one of"):
        parse_market("gold")


def test_walk_forward_window_count_is_bounded():
    assert parse_strategy_payload({"symbol": "BTC", "n_windows": 10}, include_windows=True)["n_windows"] == 10
    with pytest.raises(ValueError, match="n_windows must be between"):
        parse_strategy_payload({"symbol": "BTC", "n_windows": 11}, include_windows=True)
