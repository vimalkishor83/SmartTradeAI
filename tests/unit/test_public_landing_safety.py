"""Contract checks for the public UI-4 landing experience."""

from pathlib import Path


ROOT = Path(__file__).parents[2]
LANDING = ROOT / "frontend" / "templates" / "landing.html"
SIGNALS_API = ROOT / "app" / "api" / "v1" / "signals.py"


def test_public_landing_has_skip_navigation_and_mobile_menu_contracts():
    source = LANDING.read_text(encoding="utf-8")

    assert '<a class="skip-link" href="#mainContent">' in source
    assert '<main id="mainContent">' in source
    assert '<nav class="navbar" aria-label="Public site navigation">' in source
    assert 'id="publicNavLinks"' in source
    assert 'id="publicNavToggle"' in source
    assert 'aria-controls="publicNavLinks"' in source
    assert 'href="/static/css/public-nav.css"' in source
    assert ".nav-cta" in (ROOT / "frontend" / "static" / "css" / "public-nav.css").read_text(encoding="utf-8")
    assert "flex-wrap: nowrap" in (ROOT / "frontend" / "static" / "css" / "public-nav.css").read_text(encoding="utf-8")
    assert "nav.classList.toggle('menu-open')" in source
    assert "links.querySelectorAll('a').forEach(link => link.addEventListener('click', close))" in source
    assert 'type="button" id="backToTop"' in source
    assert '<a href="#signals" class="btn btn-outline btn-lg">View Live Signals →</a>' in source


def test_public_landing_centers_desktop_menu_and_uses_decorative_hero_asset():
    source = LANDING.read_text(encoding="utf-8")
    hero_asset = ROOT / "frontend" / "static" / "img" / "hero-market-atmosphere.png"

    assert "grid-template-columns: minmax(220px, 1fr) auto minmax(220px, 1fr);" in source
    assert "justify-self: center;" in source
    assert "url('/static/img/hero-market-atmosphere.png')" in source
    assert hero_asset.is_file()
    assert hero_asset.stat().st_size > 0


def test_public_landing_presents_a_read_only_intelligence_console():
    source = LANDING.read_text(encoding="utf-8")

    assert 'class="hero-console" aria-label="Illustrative read-only market intelligence console"' in source
    assert 'class="hero-chart-svg"' in source
    assert 'class="hero-signal-stack"' in source
    assert 'id="heroConsolePrimaryAsset"' in source
    assert 'id="heroConsolePrimaryBadge"' in source
    assert 'id="heroConsoleDataNote"' in source
    assert 'id="market-intelligence" class="intelligence-section"' in source
    assert 'aria-label="Supported market categories"' in source
    assert 'aria-label="Available analysis timeframes"' in source
    assert 'Confidence is a measure of internal indicator agreement' in source


def test_public_landing_binds_console_preview_to_bounded_public_board_data():
    source = LANDING.read_text(encoding="utf-8")

    assert "const updateHeroConsole = (row, fmt) =>" in source
    assert "setHeroConsoleText('heroConsolePrimaryAsset'" in source
    assert "setHeroConsoleText('heroConsoleEntry'" in source
    assert "setHeroConsoleText('heroConsoleTarget'" in source
    assert "setHeroConsoleText('heroConsoleDataNote'" in source
    assert "updateHeroConsole(rows[0], fmt);" in source
    assert "updateHeroConsole(null, fmt);" in source


def test_public_landing_pricing_presents_five_clear_tiers():
    source = LANDING.read_text(encoding="utf-8")
    pricing = source.split('<div class="pricing-section"', 1)[1].split('<!-- ═══ FAQ', 1)[0]

    assert pricing.count('class="pricing-card') == 5
    assert '<strong>Advanced</strong>' in pricing
    assert '<span class="currency">₹</span>1,499' in pricing
    assert '<span class="currency">₹</span>1,999' in pricing
    assert 'pricing-grid-5' in pricing
    assert 'repeat(5, minmax(112px, 1fr))' in source
    assert 'class="plan-name">Advanced</div>' in pricing
    assert '"name": "Pro", "price": "1999"' in source


def test_shared_public_nav_is_loaded_across_public_pages():
    templates = [LANDING, *sorted((ROOT / "frontend" / "templates" / "legal").glob("*.html"))]
    css = ROOT / "frontend" / "static" / "css" / "public-nav.css"

    assert css.is_file()
    css_source = css.read_text(encoding="utf-8")
    assert ".navbar .nav-cta" in css_source
    assert "flex-wrap: nowrap" in css_source
    assert "flex-basis: 100%" in css_source
    for template in templates:
        assert 'href="/static/css/public-nav.css"' in template.read_text(encoding="utf-8")


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


def test_public_dashboard_preview_is_read_only_and_sample_gated():
    source = LANDING.read_text(encoding="utf-8")
    api_source = SIGNALS_API.read_text(encoding="utf-8")
    route = api_source.split('@signals_bp.route("/public-performance"', 1)[1]
    route = route.split('@signals_bp.route("/performance/by-asset"', 1)[0]

    assert 'id="dashboard-preview"' in source
    assert "Read-only · no account data" in source
    assert "/api/v1/signals/public-performance" in source
    assert "publicPreviewWinRate" in source
    assert "publicPreviewNote" in source
    assert '@limiter.limit("30 per minute", override_defaults=True)' in route
    assert "@login_required" not in route
    assert "minimum_sample = 30" in route
    assert '"available": False' in route
    assert '"wins": wins' in route
    assert '"losses": losses' in route
