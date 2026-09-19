"""Contract checks for the split public pre-login experience."""

from pathlib import Path


ROOT = Path(__file__).parents[2]
PUBLIC = ROOT / "frontend" / "templates" / "public"
VIEWS = (ROOT / "app" / "views.py").read_text(encoding="utf-8")
PUBLIC_JS = (ROOT / "frontend" / "static" / "js" / "public-pages.js").read_text(encoding="utf-8")


def test_split_public_pages_exist_and_share_one_shell():
    expected = {
        "base.html",
        "landing.html",
        "features.html",
        "how_it_works.html",
        "live_signals.html",
        "pricing.html",
        "results.html",
        "faq.html",
    }
    assert {path.name for path in PUBLIC.glob("*.html")} >= expected

    for filename in expected - {"base.html"}:
        source = (PUBLIC / filename).read_text(encoding="utf-8")
        assert '{% extends "public/base.html" %}' in source


def test_public_pages_use_page_specific_search_descriptions():
    for filename in ("how_it_works.html", "results.html", "faq.html"):
        source = (PUBLIC / filename).read_text(encoding="utf-8")
        assert "{% block meta_description %}" in source
        assert "SmartTrade AI" in source.split("{% block meta_description %}", 1)[1].split("{% endblock %}", 1)[0]


def test_public_pages_use_page_specific_social_preview_metadata():
    for filename in ("landing.html", "features.html", "how_it_works.html", "live_signals.html", "pricing.html", "results.html", "faq.html"):
        source = (PUBLIC / filename).read_text(encoding="utf-8")
        assert "{% block og_title %}" in source
        assert "{% block og_description %}" in source


def test_public_shell_exposes_rich_social_preview_contract():
    source = (PUBLIC / "base.html").read_text(encoding="utf-8")
    assert 'property="og:image"' in source
    assert 'name="twitter:card" content="summary"' in source
    assert 'name="twitter:image"' in source


def test_public_routes_and_sitemap_contract_are_registered():
    for path in (
        "/features",
        "/how-it-works",
        "/live-signals",
        "/pricing",
        "/results",
        "/faq",
    ):
        assert f'@views_bp.route("{path}")' in VIEWS
        assert f'("{path}"' in VIEWS
        assert f'"Allow: {path}"' in VIEWS


def test_public_signal_preview_filters_non_actionable_rows_and_pauses_hidden_polling():
    assert "filter((row) => ['BUY', 'SELL'].includes" in PUBLIC_JS
    assert "safeNumber(row?.entry_price) != null" in PUBLIC_JS
    assert "formatPrice(row.stop_loss)" in PUBLIC_JS
    assert "document.visibilityState === 'hidden'" in PUBLIC_JS
    assert "window.setInterval(() => { loadTicker(); loadBoard(); }, 30000)" in PUBLIC_JS
    assert "setAttribute('aria-current', 'page')" in PUBLIC_JS
    assert "menu.classList.remove('open')" in PUBLIC_JS


def test_public_pages_have_clear_read_only_and_safety_language():
    landing = (PUBLIC / "landing.html").read_text(encoding="utf-8")
    signals = (PUBLIC / "live_signals.html").read_text(encoding="utf-8")
    pricing = (PUBLIC / "pricing.html").read_text(encoding="utf-8")

    assert "READ-ONLY PREVIEW" in landing
    assert "ILLUSTRATIVE SIGNAL CARD" in landing
    assert "Illustrative values" in landing
    for anchor in ('id="features"', 'id="how-it-works"', 'id="signals"', 'id="pricing"', 'id="faq"', 'id="about"', 'id="contact"'):
        assert anchor in landing
    assert "read-only" in signals.lower()
    assert '<caption class="public-visually-hidden">' in signals
    assert 'scope="col"' in signals
    assert 'role="status" aria-live="polite"' in signals
    assert "Paper trading by default" in pricing
    assert "not personalized investment advice" in pricing


def test_public_data_contract_and_register_plan_continuity_are_explicit():
    signals = (ROOT / "app" / "api" / "v1" / "signals.py").read_text(encoding="utf-8")
    register = (ROOT / "frontend" / "templates" / "auth" / "register.html").read_text(encoding="utf-8")

    assert '"as_of": as_of' in signals
    assert '"freshness_seconds": 30' in signals
    assert '"scope": "1h public preview"' in signals
    assert '"stop_loss": result.get("stop_loss")' in signals
    board_route = signals.split('@signals_bp.route("/public-board"', 1)[1].split('@signals_bp.route("/public-stats"', 1)[0]
    assert '@limiter.limit("30 per minute", override_defaults=True)' in board_route
    assert '@cache.cached(timeout=30, key_prefix="signals_public_board")' in board_route
    stats_route = signals.split('@signals_bp.route("/public-stats"', 1)[1].split('@signals_bp.route("/public-performance"', 1)[0]
    assert '@cache.cached(timeout=300, key_prefix="signals_public_stats")' in stats_route
    assert '"as_of": datetime.now(timezone.utc).isoformat()' in stats_route
    results = (PUBLIC / "results.html").read_text(encoding="utf-8")
    assert 'data-public-results' in results
    assert 'data-result-period' in results
    assert 'data-result-updated' in results
    assert 'data-public-performance' in PUBLIC_JS
    assert 'data.avg_pnl_pct' in PUBLIC_JS
    assert "new URLSearchParams(window.location.search).get('plan')" in register
    assert "sessionStorage.setItem('selected_plan', plan)" in register


def test_public_shell_uses_validated_optional_social_links_without_placeholders():
    shell = (PUBLIC / "base.html").read_text(encoding="utf-8")
    js = PUBLIC_JS
    assert 'data-public-social' in shell
    assert "/api/v1/public/site-config" in js
    assert "noopener noreferrer" in js


def test_legal_policy_documents_expose_consistent_review_metadata():
    for filename in ("terms.html", "privacy.html", "cookie_policy.html", "acceptable_use.html", "risk_disclosure.html", "refund_policy.html"):
        source = (ROOT / "frontend" / "templates" / "legal" / filename).read_text(encoding="utf-8")
        assert source.count('class="legal-meta-label">Effective</div>') == 1
        assert source.count('class="legal-meta-label">Review cycle</div>') == 1
        assert "September 2026" in source
