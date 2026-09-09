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


def test_terminal_layout_keeps_signal_details_scanable_at_desktop_and_mobile_widths():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert '<div class="terminal-page">' in source
    assert "isolation: isolate" in source
    assert "left: auto" in source
    assert "content: none" in source
    assert "z-index: 0" in source
    assert "margin-bottom: 12px" in source
    assert 'class="section-card terminal-toolbar mb-3"' in source
    assert 'class="row g-3 row-cols-1 row-cols-md-2 row-cols-lg-4"' in source
    assert 'term-signal-card term-card-${String(s.signal_type ||' in source
    assert 'class="sc-cell sc-cell-entry"' in source
    assert 'class="sc-cell sc-cell-stop"' in source
    assert 'sc-cell sc-cell-target' in source
    assert 'Trailing stop active after Target' in source
    assert 'Tracked setup · ${rel} · live quote' in source
    assert '@media (max-width: 767.98px)' in source
