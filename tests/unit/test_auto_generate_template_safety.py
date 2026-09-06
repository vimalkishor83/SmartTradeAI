"""Contract checks for automated signal generation controls."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "auto_generate.html"


def test_auto_generate_controls_have_explicit_button_and_status_semantics():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'id="globalStatus" class="ag-status-pill" role="status" aria-live="polite"' in source
    assert '<button type="button" class="btn btn-lg px-5 fw-700" id="startBtn"' in source
    assert '<button type="button" class="btn btn-outline-light btn-sm" id="runOnceBtn">' in source
    assert '<button type="button" class="btn btn-outline-light btn-sm" id="saveConfigBtn">' in source


def test_auto_generate_mutations_restore_controls_after_exceptions():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "async function startGeneration()" in source
    assert "async function runOnce()" in source
    assert "async function saveConfiguration()" in source
    assert source.count("btn.removeAttribute('aria-busy');") >= 3
    assert "Unable to start automatic generation right now" in source
    assert "Unable to trigger a single run right now" in source
    assert "Unable to save automatic-generation configuration" in source
