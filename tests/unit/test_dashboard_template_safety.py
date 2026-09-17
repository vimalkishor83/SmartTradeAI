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


def test_opportunity_cards_drive_the_inline_inspector_accessibly():
    source = TEMPLATE.read_text(encoding="utf-8")
    page = PAGE.read_text(encoding="utf-8")

    assert 'class="opp-card" role="button" tabindex="0" aria-expanded="false"' in source
    assert 'aria-controls="inspectorCard"' in source
    assert "mouseenter" in source
    assert "card.addEventListener('focus'" in source
    assert "card.addEventListener('click', () => inspect(true))" in source
    assert "id=\"inspectorCard\" hidden" in page
    assert 'id="inspectorClose"' in page
    assert 'id="inspOpenLink"' in page
    assert 'class="col-xl-4"' not in page
    assert "loadInspector([..._signalData]" not in source


def test_dashboard_explains_data_scope_and_refresh_state():
    source = TEMPLATE.read_text(encoding="utf-8")
    page = PAGE.read_text(encoding="utf-8")

    assert '<h1 class="page-greeting" id="pageGreeting">' in page
    assert 'id="dashboardContent" aria-busy="true"' in page
    assert 'id="dashboardDataStatus" role="status" aria-live="polite"' in page
    assert 'id="dashboardRetry"' in page
    assert 'aria-controls="dashboardContent" hidden' in page
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
    assert "retry.hidden = !['degraded', 'error'].includes(kind);" in source
    assert "retry.setAttribute('aria-busy', String(isBusy));" in source
    assert "document.getElementById('dashboardRetry')?.addEventListener('click'" in source
    assert "requestId !== _signalsRequestId" in source
    assert "requestId !== _heatmapRequestId" in source
    assert "function dashboardEmptyState(message, href, label)" in source
    assert "No active signals for this filter." in source
    assert "dashboardEmptyState('No opportunities right now.', '/markets/crypto', 'Browse Markets')" in source
    assert "link.textContent = label;" in source
    assert "stateRow" in source
    assert "Live conditions across all markets" in source
    assert "Live data updated ' + time" not in source
    assert "setAttribute('aria-labelledby', tab.id)" in source


def test_dashboard_normalizes_provider_numbers_before_rendering():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "const numberOr" in source
    assert "const safePrice" in source
    assert "const percentOr" in source
    assert "clamp(s.confidence_score, 0, 100, 0)" in source
    assert "numberOr(row?.pnl_pct)" in source
    assert "typeof Chart === 'undefined'" in source


def test_dashboard_signal_table_exposes_trade_lifecycle_context():
    source = TEMPLATE.read_text(encoding="utf-8")
    page = PAGE.read_text(encoding="utf-8")

    assert "function _signalTableStatus(signal, lifecycle, targets)" in source
    assert "ENTRY HIT" in source
    assert "TARGET 1 HIT" in source
    assert "STOP HIT" in source
    assert "const pnl = numberOr(s.pnl_pct)" in source
    assert "relativeTime(s.generated_at)" in source
    assert "<th>Status</th>" in page
    assert "<th>Stop Loss</th>" in page
    assert "<th>Target 1</th>" in page
    assert "<th>P&amp;L</th>" in page
    assert 'colspan="12"' in page
