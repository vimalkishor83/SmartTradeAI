"""Contract checks for the multi-tab technical analysis summary."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "ta_summary.html"


def test_ta_summary_uses_delegated_tabs_and_detail_controls():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "data-ta-tab=\"ratings\"" in source
    assert 'id="lastUpdated" role="status" aria-live="polite"' in source
    assert '<button type="button" class="btn btn-sm btn-outline-light" id="refreshBtn">' in source
    assert "data-ai-nav" in source
    assert "data-ema-detail-index" in source
    assert "data-action=\"close-ema-detail\"" in source
    assert "window.location.assign(`/ai-insights?asset=" in source


def test_ta_summary_escapes_market_payloads_and_validates_navigation_ids():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "function taNumber(value, fallback = 0)" in source
    assert "function taText(value)" in source
    assert "function taAssets(value)" in source
    assert "value.filter(asset => asset && typeof asset === 'object' && taAssetId(asset.id))" in source
    assert "taText(a.symbol)" in source
    assert "taText(a.name)" in source
    assert "taAssetId(assetId)" in source
    assert "taTimeframe(cell.dataset.timeframe)" in source
    assert "function taLoadError(wrapId, message)" in source
    assert "Refresh failed" in source
