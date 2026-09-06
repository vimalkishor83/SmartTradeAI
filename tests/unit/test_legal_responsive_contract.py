"""Protect navigation and reading behavior shared by standalone legal pages."""

from pathlib import Path


ROOT = Path(__file__).parents[2]
LEGAL_PAGES = tuple((ROOT / "frontend/templates/legal").glob("*.html"))


def test_every_legal_page_loads_shared_responsive_styles_and_labels_navigation():
    assert len(LEGAL_PAGES) == 8
    for page in LEGAL_PAGES:
        source = page.read_text(encoding="utf-8")
        assert "/static/css/legal.css" in source
        assert 'aria-label="Public site navigation"' in source


def test_legal_styles_keep_mobile_navigation_and_long_content_usable():
    source = (ROOT / "frontend/static/css/legal.css").read_text(encoding="utf-8")
    assert ".nav-links" in source
    assert "flex-basis: 100%" in source
    assert ".legal-doc table" in source
    assert "overflow-x: auto" in source
    assert "prefers-reduced-motion" in source


def test_legal_index_has_three_column_card_grid_and_visual_assets():
    source = (ROOT / "frontend/templates/legal/index.html").read_text(encoding="utf-8")

    assert "grid-template-columns: repeat(3, 1fr)" in source
    assert "grid-template-columns: repeat(2, 1fr)" in source
    assert ".legal-index-card:nth-child(3n + 2)::before" in source
    assert "/static/img/legal-center-atmosphere.png" in source
    assert "/static/img/markets-atmosphere.png" in source
    assert "/static/img/hero-market-atmosphere.png" in source

    for asset in (
        "legal-center-atmosphere.png",
        "markets-atmosphere.png",
        "hero-market-atmosphere.png",
    ):
        path = ROOT / "frontend/static/img" / asset
        assert path.is_file()
        assert path.stat().st_size > 0
