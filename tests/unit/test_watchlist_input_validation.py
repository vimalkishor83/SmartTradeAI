import pytest

from app.api.v1.watchlist import (
    MAX_WATCHLIST_ALERT_PRICE,
    MAX_WATCHLIST_NAME,
    _bounded_text,
    _normalize_watchlist_symbol,
    _optional_positive_float,
    _strict_bool,
)


def test_watchlist_text_is_bounded_and_normalized():
    assert _bounded_text("  Momentum  ", "name", MAX_WATCHLIST_NAME, required=True) == "Momentum"
    with pytest.raises(ValueError):
        _bounded_text("x" * (MAX_WATCHLIST_NAME + 1), "name", MAX_WATCHLIST_NAME, required=True)
    with pytest.raises(ValueError):
        _bounded_text(["not text"], "name", MAX_WATCHLIST_NAME)


def test_watchlist_symbol_rejects_malformed_json_values():
    assert _normalize_watchlist_symbol(" btc-usd ") == "BTC-USD"
    with pytest.raises(ValueError):
        _normalize_watchlist_symbol(["BTCUSD"])
    with pytest.raises(ValueError):
        _normalize_watchlist_symbol("<script>")


def test_watchlist_alert_price_is_finite_positive_and_bounded():
    assert _optional_positive_float("12.5", "alert_price", MAX_WATCHLIST_ALERT_PRICE) == 12.5
    assert _optional_positive_float(None, "alert_price", MAX_WATCHLIST_ALERT_PRICE) is None
    with pytest.raises(ValueError):
        _optional_positive_float(0, "alert_price", MAX_WATCHLIST_ALERT_PRICE)
    with pytest.raises(ValueError):
        _optional_positive_float(float("nan"), "alert_price", MAX_WATCHLIST_ALERT_PRICE)
    with pytest.raises(ValueError):
        _optional_positive_float(MAX_WATCHLIST_ALERT_PRICE + 1, "alert_price", MAX_WATCHLIST_ALERT_PRICE)


def test_watchlist_repeat_flag_requires_real_boolean():
    assert _strict_bool(True, "alert_repeat") is True
    assert _strict_bool(None, "alert_repeat") is False
    with pytest.raises(ValueError):
        _strict_bool("false", "alert_repeat")
