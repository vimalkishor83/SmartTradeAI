"""Contract checks for the model performance dashboard."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "model_performance.html"


def test_model_performance_controls_are_event_bound():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "oninput=" not in source
    assert 'data-action="refresh-performance"' in source
    assert "addEventListener('click', loadPerf)" in source
    assert 'id="modelPerformanceStatus" class="visually-hidden" role="status" aria-live="polite"' in source


def test_model_performance_uses_bounded_dynamic_values():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "function safeCount(value" in source
    assert "function safeStats(value)" in source
    assert "Number.isFinite(numeric)" in source
    assert "safeCount(s.total)" in source
    assert "escapeHtml(a.symbol)" in source
    assert "if (typeof Chart !== 'function')" in source


def test_model_performance_guards_refresh_and_chart_state():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "let _perfLoadSequence = 0;" in source
    assert "let _perfRequestInFlight = false;" in source
    assert "if (_perfRequestInFlight) return;" in source
    assert "if (sequence !== _perfLoadSequence) return;" in source
    assert "refreshButton.disabled = true;" in source
    assert "Existing values, if any, may be stale." in source
