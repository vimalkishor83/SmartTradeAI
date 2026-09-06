"""Contract checks for live values rendered by the Dashboard page."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "static" / "js" / "pages" / "dashboard.js"
PAGE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "index.html"


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


def test_dashboard_explains_data_scope_and_refresh_state():
    source = TEMPLATE.read_text(encoding="utf-8")
    page = PAGE.read_text(encoding="utf-8")

    assert 'id="dashboardContent" aria-busy="true"' in page
    assert 'id="dashboardDataStatus" role="status" aria-live="polite"' in page
    assert 'Last 100 closed' in page
    assert "Today's Summary <span class=\"text-muted fw-normal\">(UTC)" in page
    assert 'role="tablist"' in page
    assert 'aria-selected="true"' in page
    assert 'role="tabpanel"' in page
    assert 'aria-labelledby="heatmapTabChange"' in page
    assert "Promise.allSettled" in source
    assert "_dashboardLoadPromise" in source
    assert "setDashboardBusy(true)" in source
    assert "Dashboard partially updated" in source
    assert "requestId !== _signalsRequestId" in source
    assert "requestId !== _heatmapRequestId" in source
    assert "stateRow" in source
    assert "setAttribute('aria-labelledby', tab.id)" in source


def test_dashboard_normalizes_provider_numbers_before_rendering():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "const numberOr" in source
    assert "const safePrice" in source
    assert "const percentOr" in source
    assert "clamp(s.confidence_score, 0, 100, 0)" in source
    assert "numberOr(row?.pnl_pct)" in source
    assert "typeof Chart === 'undefined'" in source
