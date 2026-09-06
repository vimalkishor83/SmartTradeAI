import pytest

from app.api.v1.portfolio import (
    MAX_PORTFOLIO_NOTES,
    MAX_PORTFOLIO_PRICE,
    MAX_PORTFOLIO_QUANTITY,
    _normalize_symbol,
    _optional_positive_float,
    _portfolio_notes,
    _positive_float,
)


def test_positive_float_rejects_non_finite_and_non_positive_values():
    with pytest.raises(ValueError):
        _positive_float(float("nan"), "quantity")
    with pytest.raises(ValueError):
        _positive_float(0, "quantity")
    with pytest.raises(ValueError):
        _positive_float(-1, "quantity")


def test_optional_positive_float_allows_clearing_a_level():
    assert _optional_positive_float(None, "stop_loss") is None
    assert _optional_positive_float("", "stop_loss") is None
    assert _optional_positive_float("95.5", "stop_loss") == 95.5


def test_positive_float_enforces_portfolio_bounds():
    assert _positive_float(MAX_PORTFOLIO_QUANTITY, "quantity", MAX_PORTFOLIO_QUANTITY) == MAX_PORTFOLIO_QUANTITY
    with pytest.raises(ValueError):
        _positive_float(MAX_PORTFOLIO_QUANTITY + 1, "quantity", MAX_PORTFOLIO_QUANTITY)
    with pytest.raises(ValueError):
        _optional_positive_float(MAX_PORTFOLIO_PRICE + 1, "target", MAX_PORTFOLIO_PRICE)


def test_symbol_normalization_rejects_non_strings_and_unsafe_shapes():
    assert _normalize_symbol("  btc-usdt ") == "BTC-USDT"
    with pytest.raises(ValueError):
        _normalize_symbol(["BTCUSDT"])
    with pytest.raises(ValueError):
        _normalize_symbol("<script>")
    with pytest.raises(ValueError):
        _normalize_symbol("A" * 31)


def test_notes_match_database_column_contract():
    assert _portfolio_notes("  trade plan  ") == "trade plan"
    assert _portfolio_notes("x" * MAX_PORTFOLIO_NOTES) == "x" * MAX_PORTFOLIO_NOTES
    with pytest.raises(ValueError):
        _portfolio_notes("x" * (MAX_PORTFOLIO_NOTES + 1))
    with pytest.raises(ValueError):
        _portfolio_notes({"unexpected": "object"})
