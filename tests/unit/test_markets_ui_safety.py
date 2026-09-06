"""Contract checks for the stable Markets overview and refresh workflow."""

from pathlib import Path


ROOT = Path(__file__).parents[2]
TEMPLATE = ROOT / "frontend" / "templates" / "markets" / "index.html"
SCRIPT = ROOT / "frontend" / "static" / "js" / "pages" / "markets.js"


def test_markets_page_exposes_live_context_and_accessible_filter_controls():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'id="marketsContext" role="status" aria-live="polite"' in source
    assert 'id="marketsContent" role="tabpanel"' in source
    assert 'id="mktTabs" role="tablist"' in source
    assert 'id="marketTabAll" role="tab"' in source
    assert 'id="marketsUpdatedAt"' in source
    assert '<label class="visually-hidden" for="tfFilter">' in source
    assert '<label class="visually-hidden" for="typeFilter">' in source
    assert '<label class="visually-hidden" for="assetSearch">' in source
    assert 'class="search-bar-clear" aria-label="Clear asset search"' in source
    assert '<caption class="visually-hidden">Live signals' in source


def test_markets_controller_bounds_values_and_serializes_refreshes():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "const mnum =" in source
    assert "const mcount =" in source
    assert "const mpercent =" in source
    assert "let _marketsRefreshPromise = null;" in source
    assert "let _marketsRefreshQueued = false;" in source
    assert "let _marketsSelectionSequence = 0;" in source
    assert "Promise.allSettled(loaders.map(loader => loader()))" in source
    assert "if (!_marketIsCurrent(sequence)) return null;" in source
    assert "function _setMarketStatus(state, message, detail)" in source
    assert "function _setActiveTab()" in source
    assert "t.setAttribute('aria-selected', selected ? 'true' : 'false');" in source


def test_markets_controller_reports_partial_provider_failures():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "Live signals are temporarily unavailable." in source
    assert "AI scores are temporarily unavailable." in source
    assert "News impact is temporarily unavailable." in source
    assert "Economic events are temporarily unavailable." in source
    assert "data is partially available" in source
