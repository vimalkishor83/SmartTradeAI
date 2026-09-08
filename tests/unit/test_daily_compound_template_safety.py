"""Contract checks for the daily compound calculator responsive shell."""

from pathlib import Path


TEMPLATE = (
    Path(__file__).parents[2]
    / "frontend"
    / "templates"
    / "admin"
    / "daily_compound_calculator.html"
)


def test_calculator_has_mobile_safe_input_and_results_regions():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'class="row g-4 dcc-layout"' in source
    assert 'class="col-lg-4 dcc-input-column"' in source
    assert 'class="col-lg-8 dcc-results-column"' in source
    assert 'class="dcc-action-row"' in source
    assert "dcc-schedule-wrap" in source
    assert "grid-template-columns:1fr" in source


def test_calculator_result_panel_has_clear_empty_and_loaded_states():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "Your projection will appear here" in source
    assert "Projected outcome" in source
    assert "Growth schedule" in source
    assert "Switch views to inspect the projection" in source


def test_save_panel_is_mobile_safe_and_keyboard_dismissible():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'role="dialog" aria-modal="true"' in source
    assert 'id="pClose"' in source
    assert "function setPanelOpen(open)" in source
    assert "setAttribute('aria-hidden', String(!open))" in source
    assert "e.key === 'Escape'" in source
    assert "width:100%; max-width:100%" in source
