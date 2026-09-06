"""Contract checks for resilient My Performance rendering."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "performance.html"


def test_performance_exposes_historical_context_and_accessible_charts():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'id="performanceStatus" role="status" aria-live="polite"' in source
    assert 'id="refreshPerf" aria-controls="kpiRow" aria-busy="false"' in source
    assert 'role="img" aria-label="Historical win rate by timeframe chart"' in source
    assert '<caption class="visually-hidden">Historical performance by confidence bucket</caption>' in source
    assert '<caption class="visually-hidden">Terminal live-read performance by timeframe</caption>' in source


def test_performance_normalizes_partial_payloads_and_serializes_refreshes():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "function performanceNumber(value, fallback = 0)" in source
    assert "function performanceCount(value)" in source
    assert "function performanceRate(value)" in source
    assert "function performanceRows(value)" in source
    assert "let _performanceRefreshPromise = null;" in source
    assert "Promise.allSettled([loadPerformance(), loadLiveReadPerformance()])" in source
    assert "Some performance data is unavailable. Try refreshing." in source
    assert "escapeHtml(String(r.timeframe ?? 'Unknown'))" in source
