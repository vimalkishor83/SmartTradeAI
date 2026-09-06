"""Contract checks for the public UI-4 landing experience."""

from pathlib import Path


ROOT = Path(__file__).parents[2]
LANDING = ROOT / "frontend" / "templates" / "landing.html"


def test_public_landing_has_skip_navigation_and_mobile_menu_contracts():
    source = LANDING.read_text(encoding="utf-8")

    assert '<a class="skip-link" href="#mainContent">' in source
    assert '<main id="mainContent">' in source
    assert '<nav class="navbar" aria-label="Public site navigation">' in source
    assert 'id="publicNavLinks"' in source
    assert 'id="publicNavToggle"' in source
    assert 'aria-controls="publicNavLinks"' in source
    assert "nav.classList.toggle('menu-open')" in source
    assert "links.querySelectorAll('a').forEach(link => link.addEventListener('click', close))" in source
    assert 'type="button" id="backToTop"' in source
    assert '<a href="#signals" class="btn btn-outline btn-lg">View Live Signals →</a>' in source


def test_public_live_data_is_bounded_escaped_and_does_not_overlap_polling():
    source = LANDING.read_text(encoding="utf-8")

    assert "function publicSafe(value)" in source
    assert "function publicNumber(value, fallback = null)" in source
    assert "let landingTickerInFlight = false" in source
    assert "if (!track || landingTickerInFlight) return;" in source
    assert ".slice(0, 12)" in source
    assert ".slice(0, 5)" in source
    assert "symbol: publicSafe(it?.symbol || 'Market')" in source
    assert '<div class="sig-asset">${r.asset}</div>' not in source
    assert "valueEl.innerHTML = `<span class=\"num\">" not in source
    assert 'href="${url}"' not in source


def test_public_first_paint_storage_and_live_error_paths_are_safe():
    source = LANDING.read_text(encoding="utf-8")

    assert "try { token = localStorage.getItem('access_token'); } catch (_) {}" in source
    assert "if (!res.ok) throw new Error('ticker request failed');" in source
    assert "if (timeout) clearTimeout(timeout);" in source
    assert "landingTickerInFlight = false;" in source
    assert 'role="region" aria-label="Live market prices"' in source
