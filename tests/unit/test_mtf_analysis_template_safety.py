"""Contract checks for the Multi-Timeframe Analysis refresh lifecycle."""

from pathlib import Path


TEMPLATE = (
    Path(__file__).parents[2]
    / "frontend"
    / "templates"
    / "dashboard"
    / "mtf_analysis.html"
)


def test_mtf_analysis_exposes_semantic_refresh_and_status_controls():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert '<button type="button" class="btn btn-sm btn-outline-light" id="refreshBtn">' in source
    assert 'id="matrixStatus" class="px-3 pt-2 text-muted fs-xs" role="status" aria-live="polite"' in source


def test_mtf_analysis_recovers_from_matrix_refresh_failures():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "async function loadMatrix(showSpinner = true)" in source
    assert "Unable to refresh the matrix. Showing the last available data." in source
    assert "No matrix data is available right now. Try Refresh." in source
    assert "button.removeAttribute('aria-busy');" in source
