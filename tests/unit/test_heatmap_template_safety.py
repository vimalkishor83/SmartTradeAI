"""Contract checks for the market heatmap UI."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "heatmap.html"


def test_heatmap_uses_event_bound_controls():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "data-view=\"compact\"" in source
    assert "data-view=\"normal\"" in source
    assert 'id="hmRefreshBtn"' in source
    assert "btn.addEventListener('click', () => setView(btn.dataset.view))" in source


def test_heatmap_escapes_provider_values_and_validates_navigation():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "${item.symbol}" not in source
    assert "${item.name}" not in source
    assert "window.location.href = `/asset/${item.asset_id || ''}`" not in source
    assert "function _hmHtml(value)" in source
    assert "_hmHtml(item.symbol || '—')" in source
    assert "_hmHtml(item.name || '—')" in source
    assert "function _hmAssetHref(value)" in source


def test_heatmap_bounds_data_and_serializes_refreshes():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "function _hmNumber(value, fallback = 0)" in source
    assert "Array.isArray(items) ? items : []" in source
    assert "Array.isArray(_hmData) ? _hmData : []" in source
    assert "let _hmLoadPromise = null;" in source
    assert "if (_hmLoadPromise) return _hmLoadPromise;" in source
    assert "if (!Array.isArray(data?.heatmap) || data.error)" in source


def test_heatmap_exposes_loading_and_accessible_view_state():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'id="heatmapContext"' in source
    assert 'id="heatmapStatus"' in source
    assert 'aria-busy="true"' in source
    assert 'aria-pressed="true"' in source
    assert "body.setAttribute('aria-busy', 'false')" in source
    assert "if (_hmBooted) return;" in source
