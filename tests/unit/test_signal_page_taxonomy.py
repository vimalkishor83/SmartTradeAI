"""Regression checks for the signal-page information architecture."""

from pathlib import Path


ROOT = Path(__file__).parents[2]
TEMPLATES = ROOT / "frontend" / "templates"


def _read(relative_path):
    return (TEMPLATES / relative_path).read_text(encoding="utf-8")


def test_primary_signal_pages_use_distinct_product_names():
    base = _read("partials/base.html")
    signals = _read("dashboard/signals.html")
    scanner = _read("dashboard/scanner.html")
    ta_summary = _read("dashboard/ta_summary.html")
    mtf = _read("dashboard/mtf_analysis.html")

    assert "Signal Center" in base
    assert "Technical Ratings" in base
    assert "Timeframe Confluence" in base
    assert "Signal Center" in signals
    assert "Market Discovery Scanner" in scanner
    assert "Technical Ratings" in ta_summary
    assert "Timeframe Confluence" in mtf


def test_signal_center_exposes_a_clear_next_step_workflow():
    source = _read("dashboard/signals.html")

    assert 'aria-label="Signal workflow"' in source
    assert 'href="/scanner"' in source
    assert '>Discover</a>' in source
    assert 'href="/signals"' in source
    assert '>Validate</a>' in source
    assert 'href="/ai-insights"' in source
    assert '>Investigate</a>' in source
    assert 'href="/risk"' in source
    assert '>Manage risk</a>' in source


def test_discovery_scanner_sets_expectations_before_trading():
    source = _read("dashboard/scanner.html")

    assert "Screening Matches" in source
    assert "exploratory filter results" in source
    assert "not persisted actionable signals" in source
    assert 'href="/signals">Signal Center</a>' in source
