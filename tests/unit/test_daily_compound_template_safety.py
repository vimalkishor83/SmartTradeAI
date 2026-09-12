"""Contract checks for the daily compound calculator responsive shell."""

from pathlib import Path


TEMPLATE = (
    Path(__file__).parents[2]
    / "frontend"
    / "templates"
    / "admin"
    / "daily_compound_calculator.html"
)
SHELL_CSS = Path(__file__).parents[2] / "frontend" / "static" / "css" / "main.css"


def test_calculator_has_mobile_safe_input_and_results_regions():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'class="row g-4 dcc-layout"' in source
    assert 'class="col-lg-4 dcc-input-column"' in source
    assert 'class="col-lg-8 dcc-results-column"' in source
    assert 'class="dcc-action-row"' in source
    assert "dcc-schedule-wrap" in source
    assert 'class="smart-table dcc-schedule-table"' in source
    assert "data-mobile-cards" not in source
    assert "Swipe horizontally to view all columns." in source
    assert "grid-template-columns:1fr" in source


def test_calculator_result_panel_has_clear_empty_and_loaded_states():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "Your projection will appear here" in source
    assert "Projected outcome" in source
    assert "fmtOutcome" in source
    assert "Cr" in source
    assert "white-space:nowrap" in source
    assert "grid-template-columns:42px minmax(0, 1fr)" in source
    assert "Growth schedule" in source
    assert "Switch views to inspect the projection" in source
    assert "position:sticky; left:0" in source


def test_mobile_toolbar_does_not_create_horizontal_overflow():
    source = SHELL_CSS.read_text(encoding="utf-8")

    assert "@media (max-width: 768px)" in source
    assert ".app-shell .cmd-trigger" in source
    assert "flex: 0 0 36px" in source
    assert "min-width: 36px" in source


def test_save_panel_is_mobile_safe_and_keyboard_dismissible():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'role="dialog" aria-modal="true"' in source
    assert 'id="pClose"' in source
    assert "function setPanelOpen(open)" in source
    assert "setAttribute('aria-hidden', String(!open))" in source
    assert "e.key === 'Escape'" in source
    assert "width:100%; max-width:100%" in source
