"""Contract checks for live values rendered by the Dashboard page."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "static" / "js" / "pages" / "dashboard.js"


def test_dashboard_escapes_live_values_and_avoids_inline_navigation():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert '<div class="opp-name">${s.asset}' not in source
    assert '<span class="text-muted">${note}' not in source
    assert "${s.regime || 'Not classified'}" not in source
    assert "${r.text}" not in source
    assert "${item.symbol}" not in source
    assert "onclick=\"location='/asset/${" not in source
    assert "onclick=\"location='/markets/${" not in source
    assert "STSafe.assetHref(s.asset_id)" in source
    assert "STSafe.marketHref(item.market)" in source
    assert "STSafe.html(r.text)" in source


def test_dashboard_rows_remain_keyboard_navigable_after_inline_handler_removal():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'tabindex="0"' in source
    assert "data-asset-href" in source
    assert "event.key === 'Enter' || event.key === ' '" in source
