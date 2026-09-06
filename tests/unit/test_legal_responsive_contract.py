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
