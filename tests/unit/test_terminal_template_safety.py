"""Contract checks for the live Markets Terminal surface."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "markets" / "terminal.html"


def test_terminal_escapes_dynamic_cards_and_validates_asset_links():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'data-tf="{{ tf }}"' not in source
    assert 'data-tf="{{ tf|e }}"' in source
    assert 'href="/asset/${s.asset_id}"' not in source
    assert 'href="${_termAssetHref(assetId)}"' in source
    assert "${s.asset}</" not in source
    assert "${s.message ||" not in source
    assert "function _termHtml(value)" in source
    assert "function _termAssetId(value)" in source


def test_terminal_bounds_numbers_and_local_pin_storage():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "function _termNumber(value, fallback = null)" in source
    assert "function _termPercent(value)" in source
    assert "Number.isSafeInteger(e.id)" in source
    assert "Array.isArray(cards) ? cards : []" in source
    assert "const _termLoading = new Map();" in source
    assert "if (existing) return existing;" in source


def test_terminal_rejects_stale_requests_and_untrusted_controls():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "if (requestId !== _termRequestSequence) return;" in source
    assert "if (!data || data.error)" in source
    assert "const market = _termMarketKey(tab.dataset.market);" in source
    assert "const tf = _termTimeframe(tab.dataset.tf);" in source


def test_terminal_controls_are_keyboard_accessible_and_expose_busy_state():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'id="terminalMarketTabs" role="tablist"' in source
    assert 'id="terminalTfTabs" role="tablist"' in source
    assert 'id="terminalMarketCrypto" role="tab" aria-selected="true"' in source
    assert 'id="terminalGrid" role="tabpanel"' in source
    assert 'aria-live="polite" aria-busy="true"' in source
    assert 'aria-label="Refresh terminal signals"' in source
    assert '<label class="visually-hidden" for="terminalSearch">Search terminal assets</label>' in source
    assert 'aria-label="Clear terminal asset search"' in source
    assert "function _setTerminalBusy(busy)" in source
    assert "function _wireTerminalTabKeyboard(selector)" in source
    assert "document.body.dataset.terminalBooted === 'true'" in source
