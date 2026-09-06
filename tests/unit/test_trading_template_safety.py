"""Contract checks for the real-money trading page."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "trading.html"


def test_trading_table_values_are_escaped_and_cancellation_is_dataset_bound():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'onclick="cancelOrder(' not in source
    assert 'data-cancel-order="${_tradeId(o.id)}"' in source
    assert 'data-cancel-product="${_tradeId(o.product_id)}"' in source
    assert "${o.product_symbol || '—'}" not in source
    assert "${_tradeHtml(o.product_symbol || '—')}" in source
    assert "function _tradeHtml(value)" in source


def test_trading_actions_and_refreshes_are_serialized():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "let _connectionCheckPromise = null;" in source
    assert "let _loadAllPromise = null;" in source
    assert "let _placeOrderInFlight = false;" in source
    assert "const _cancelOrderInFlight = new Set();" in source
    assert "if (_placeOrderInFlight) return;" in source
    assert "_cancelOrderInFlight.has(key)) return;" in source
    assert "Promise.allSettled([" in source


def test_trading_form_mirrors_server_limits_and_validates_prefill():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'max="10000000"' in source
    assert "Number(size) > 10000000" in source
    assert "Number(leverage) > 200" in source
    assert "syncLimitPriceRequirement();" in source
    assert "if (/^[A-Z0-9]{2,40}$/.test(symbol))" in source
