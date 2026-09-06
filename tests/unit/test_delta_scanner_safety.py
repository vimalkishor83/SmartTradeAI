"""Contract checks for the shared Delta Scanner modes."""

from pathlib import Path


SCANNER = Path(__file__).parents[2] / "frontend" / "static" / "js" / "pages" / "delta_scanner.js"


def test_delta_scanner_escapes_provider_values_and_trade_links():
    source = SCANNER.read_text(encoding="utf-8")

    assert "${r.symbol}" not in source
    assert "${r.short_name}" not in source
    assert "${r.description}" not in source
    assert 'href="/trading?symbol=${tradeSym}' not in source
    assert "STSafe.html(r.symbol)" in source
    assert "STSafe.html(r.short_name || '')" in source
    assert "STSafe.assetId(existing?.id)" in source
    assert "encodeURIComponent(tradeSym)" in source
    assert "Object.create(null)" in source


def test_delta_scanner_validates_payloads_and_serializes_requests():
    source = SCANNER.read_text(encoding="utf-8")

    assert "const SC_ASSET_TYPES = new Set" in source
    assert "Object.prototype.hasOwnProperty.call(market_screener_presets_cache, presetKey)" in source
    assert "Array.isArray(data.results)" in source
    assert "Array.isArray(data.conditions_summary)" in source
    assert "if (mtfCommonInFlight) return;" in source
    assert "if (dsScanInFlight) return;" in source
    assert "if (scApplyInFlight) return;" in source
    assert "if (icApplyInFlight) return;" in source
    assert "if (ccSaveInFlight) return;" in source
    assert "finally {\n    dsScanInFlight = false;" in source


def test_delta_scanner_saved_screens_and_conditions_are_safe_to_render():
    source = SCANNER.read_text(encoding="utf-8")

    assert "STSafe.html(s.name || 'Unnamed screen')" in source
    assert "STSafe.html(assetType.replace('_', ' '))" in source
    assert "STSafe.html(c.low)" in source
    assert "STSafe.html(c.high)" in source
    assert "STSafe.html(icIndicators[f] || f)" in source
    assert "Number(r.indicators?.[f])" in source
