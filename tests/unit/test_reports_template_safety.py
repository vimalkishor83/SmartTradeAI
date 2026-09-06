"""Contract checks for the date-aware Reporting Center."""

from pathlib import Path


ROOT = Path(__file__).parents[2]
PAGE = ROOT / "frontend" / "templates" / "dashboard" / "reports.html"
SCRIPT = ROOT / "frontend" / "static" / "js" / "pages" / "reports.js"


def test_reporting_center_has_explicit_date_scope_and_states():
    page = PAGE.read_text(encoding="utf-8")

    assert 'id="reportPreset"' in page
    assert 'id="reportFrom"' in page
    assert 'id="reportTo"' in page
    assert 'id="reportValidation" role="alert"' in page
    assert 'id="reportStatus" role="status" aria-live="polite"' in page
    assert 'Historical closed trades only' in page
    assert 'Export Range CSV' in page
    assert 'caption class="ui-visually-hidden"' in page
    assert 'id="reportDailyChart" role="img"' in page


def test_reporting_center_bounds_ranges_and_provider_values():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "function validateReportRange()" in source
    assert "days > 367" in source
    assert "API.get('/signals/report', range)" in source
    assert "reportEsc" in source
    assert "reportCount" in source
    assert "reportRate" in source
    assert "reportPnl" in source
    assert "setReportTableState" in source
    assert "typeof Chart !== 'function'" in source


def test_reporting_center_serializes_loading_and_export_lifecycle():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "let _reportSequence = 0;" in source
    assert "let _reportInFlight = false;" in source
    assert "if (_reportInFlight) return;" in source
    assert "sequence !== _reportSequence" in source
    assert "API.headers()" in source
    assert "URL.revokeObjectURL(url)" in source
