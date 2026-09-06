"""Contract checks for the shared navigation and ticker shell."""

from pathlib import Path


ROOT = Path(__file__).parents[2]
BASE = ROOT / "frontend" / "templates" / "partials" / "base.html"
APP = ROOT / "frontend" / "static" / "js" / "app.js"


def test_shared_shell_uses_bound_controls_instead_of_inline_click_handlers():
    source = BASE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert source.count('class="nav-group-header" data-nav-group-toggle') == 8
    assert '<span class="nav-section-label">Signals &amp; Discovery</span>' in source
    assert '<span class="nav-section-label">AI &amp; Analysis</span>' in source
    assert '<span class="nav-section-label">Research</span>' in source
    assert '<span class="nav-section-label">Account</span>' in source
    assert 'id="navGroupBodyResearch"' in source
    assert 'id="navGroupBodyAccount"' in source
    assert 'id="navAutoGenerate"' in source
    assert "'dhan_indices'" in source.split("{% set grp_markets", 1)[1].split("%}", 1)[0]
    assert source.index('data-group="markets"') < source.index('href="/dhan-indices"') < source.index('data-group="signals"')
    assert source.count('data-tooltip="Account Settings"') == 1
    assert source.count('data-tooltip="Help &amp; FAQ"') == 1
    assert "header.addEventListener('click', () => toggleNavGroup(header))" in source
    assert 'id="tickerToggleBtn"' in source
    assert 'aria-controls="tickerStrip"' in source


def test_ticker_toggle_has_accessible_state_and_storage_fallbacks():
    source = APP.read_text(encoding="utf-8")

    assert "btn.addEventListener('click', toggleTickerStrip)" in source
    assert "btn.dataset.bound" in source
    assert "btn.setAttribute('aria-expanded', String(!collapsed))" in source
    assert "try { localStorage.setItem(TICKER_COLLAPSE_KEY" in source
    assert "try { collapsed = localStorage.getItem(TICKER_COLLAPSE_KEY) === '1'; } catch {}" in source
