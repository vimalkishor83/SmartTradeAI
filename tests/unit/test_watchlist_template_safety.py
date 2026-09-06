"""Contract checks for Watchlist rendering and action wiring."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "watchlist.html"


def test_watchlist_uses_delegated_actions_without_inline_handlers():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "data-open-add=\"${id}\"" in source
    assert "data-delete-watchlist=\"${id}\"" in source
    assert "data-remove-watchlist-item=\"${itemId}\"" in source
    assert "watchlistsContainer').addEventListener('click'" in source


def test_watchlist_escapes_live_values_and_validates_numeric_inputs():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "function _watchlistHtml(value)" in source
    assert "function _watchlistId(value)" in source
    assert "function _watchlistNumber(value, fallback = null)" in source
    assert "_watchlistHtml(symbol)" in source
    assert "_watchlistHtml(confluence)" in source
    assert "MAX_WATCHLIST_ALERT_PRICE = 1000000000000" in source
    assert "Number.isFinite(number)" in source


def test_watchlist_coalesces_refreshes_and_reports_mutation_failures():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "let _watchlistLoadPromise = null;" in source
    assert "let _contextLoadPromise = null;" in source
    assert "if (_addAssetInFlight) return;" in source
    assert "Unable to remove asset" in source
    assert "Unable to delete watchlist" in source
