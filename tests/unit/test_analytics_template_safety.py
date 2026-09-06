"""Contract checks for the read-only signal analytics dashboard."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "analytics.html"


def test_analytics_exports_are_dataset_bound():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert 'data-export-url="/api/v1/signals/export/csv"' in source
    assert 'data-export-url="/api/v1/signals/history/export/csv"' in source
    assert "window.open(url, '_blank', 'noopener')" in source


def test_analytics_bounds_and_escapes_provider_values():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "function analyticsNumber(value, fallback = 0)" in source
    assert "function analyticsCount(value)" in source
    assert "function safeRate(value)" in source
    assert "escapeHtml(String(a.symbol" in source
    assert "analyticsCount(r.total)" in source
    assert "Math.min(total, analyticsCount(a.wins))" in source


def test_analytics_serializes_refresh_and_chart_lifecycle():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "let _analyticsLoadSequence = 0;" in source
    assert "let _analyticsRequestInFlight = false;" in source
    assert "if (_analyticsRequestInFlight) return;" in source
    assert "if (sequence !== _analyticsLoadSequence) return;" in source
    assert "typeof Chart !== 'function'" in source


def test_analytics_exposes_historical_context_and_announced_state():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'id="analyticsStatus" role="status" aria-live="polite"' in source
    assert 'aria-busy="false"' in source
    assert 'role="img" aria-label="Historical win rate by market chart"' in source
    assert '<caption class="visually-hidden">Historical win rate by timeframe</caption>' in source
    assert "Loading historical signal analytics…" in source
    assert "Historical analytics are unavailable. Try refreshing." in source
