"""Contract checks for safe Scanner rendering and request handling."""

from pathlib import Path


SCANNER = Path(__file__).parents[2] / "frontend" / "static" / "js" / "pages" / "scanner.js"


def test_scanner_escapes_provider_values_and_validates_asset_links():
    source = SCANNER.read_text(encoding="utf-8")

    assert "${r.symbol}" not in source
    assert "${r.market}" not in source
    assert 'href="/asset/${aid}"' not in source
    assert "STSafe.html(r.symbol)" in source
    assert "STSafe.html(String(r.market || '').replace('_', ' '))" in source
    assert "STSafe.assetHref(aid)" in source
    assert "STSafe.assetId(_symbolIds[sym])" in source
    assert "Object.create(null)" in source


def test_scanner_handles_malformed_data_and_duplicate_actions():
    source = SCANNER.read_text(encoding="utf-8")

    assert "const _num = (value, fallback = 0)" in source
    assert "Array.isArray(r.matched_filters)" in source
    assert "if (_scanInFlight) return;" in source
    assert "try {\n    data = await API.post('/scanner/run'" in source
    assert "finally {\n    _scanInFlight = false;" in source
    assert "if (res && !res.error) _notify" in source
    assert "const _notify = (message, type = 'info')" in source


def test_scanner_reports_request_state_and_isolates_kpi_failures():
    source = SCANNER.read_text(encoding="utf-8")

    assert "let _scanBooted = false;" in source
    assert "Promise.allSettled" in source
    assert "if (!data || data.error || !Array.isArray(data.results))" in source
    assert "sset('scanStatus', 'Unable to run scan')" in source
    assert "btn.setAttribute('aria-busy', 'true')" in source


def test_scanner_csv_export_quotes_cells_and_revokes_blob_urls():
    source = SCANNER.read_text(encoding="utf-8")

    assert "const csvCell = value =>" in source
    assert "text.replace(/\"/g, '\"\"')" in source
    assert "if (typeof value === 'string' && /^[=+\\-@]/.test(text))" in source
    assert "URL.revokeObjectURL(a.href)" in source
