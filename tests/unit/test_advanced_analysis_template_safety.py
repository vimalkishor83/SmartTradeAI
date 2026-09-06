from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "advanced_analysis.html"


def test_advanced_analysis_uses_accessible_delegated_controls():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "onchange=" not in source
    assert 'id="aaTabs"' in source
    assert 'id="tfButtons"' in source
    assert "event.target?.closest?.('.aa-tab')" in source
    assert "event.target?.closest?.('.tf-btn')" in source
    assert 'aria-label="Select asset"' in source


def test_advanced_analysis_bounds_and_escapes_external_values():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "function aaNumber(value" in source
    assert "function aaEscape(value)" in source
    assert "slice(0, 500)" in source
    assert "slice(0, 100)" in source
    assert "candlesByTime" in source
    assert "textContent = `${String(a.symbol" in source
    assert "aaEscape(f.type)" in source
    assert "aaEscape(ob.type)" in source
    assert "function renderFvgOverlay(fvgs)" in source
    assert "function renderObOverlay(obs)" in source


def test_advanced_analysis_guards_chart_requests_and_series_order():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "let _aaRunSequence = 0;" in source
    assert "let _aaRunInFlight = false;" in source
    assert "let _aaBootBound = false;" in source
    assert "if (_aaRunInFlight) return;" in source
    assert "Promise.all([" in source
    assert "const pointsByTime = new Map();" in source
    assert "const markersByTime = new Map();" in source
    assert "zoneLines.forEach" in source
