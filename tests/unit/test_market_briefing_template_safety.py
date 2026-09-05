"""Contract checks for provider values rendered by overview pages."""

from pathlib import Path


STATIC_JS = Path(__file__).parents[2] / "frontend" / "static" / "js"


def test_shared_ui_sanitizer_allowlists_urls_and_asset_ids():
    source = (STATIC_JS / "app.js").read_text(encoding="utf-8")

    assert "window.STSafe" in source
    assert "['http:', 'https:'].includes(url.protocol)" in source
    assert "return /^\\d+$/.test(id) ? id : '';" in source
    assert "function signalBadge(type)" in source
    assert "STSafe.html(label)" in source


def test_markets_page_escapes_provider_values_and_avoids_inline_navigation():
    source = (STATIC_JS / "pages" / "markets.js").read_text(encoding="utf-8")

    assert "${s.asset}" not in source
    assert "${e.title}" not in source
    assert "${n.title}" not in source
    assert "${n.url}" not in source
    assert "onclick=\"location='/asset/${" not in source
    assert "STSafe.externalUrl(n.url)" in source
    assert "STSafe.assetHref(s.asset_id)" in source


def test_briefing_page_escapes_provider_values_and_uses_safe_links():
    source = (STATIC_JS / "pages" / "briefing.js").read_text(encoding="utf-8")

    assert "${m.symbol}" not in source
    assert "${m.name || ''}" not in source
    assert "${c.symbol}" not in source
    assert "${n.title || ''}" not in source
    assert "${n.url || '#'}" not in source
    assert "${e.title || ''}" not in source
    assert "${e.previous ?? '—'}" not in source
    assert "${e.forecast ?? '—'}" not in source
    assert "STSafe.externalUrl(n.url)" in source
    assert "STSafe.assetId(asset.asset_id)" in source
