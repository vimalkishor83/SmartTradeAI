"""Contract checks for the Signal Journal loading and refresh lifecycle."""

from pathlib import Path


TEMPLATE = (
    Path(__file__).parents[2]
    / "frontend"
    / "templates"
    / "dashboard"
    / "signal_journal.html"
)


def test_signal_journal_controls_expose_button_and_status_semantics():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert '<button type="button" class="btn btn-sm btn-primary" id="sjRefresh">' in source
    assert 'id="sjCount" role="status" aria-live="polite"' in source


def test_signal_journal_refresh_restores_control_after_request_exception():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "async function loadJournal()" in source
    assert "catch (_)" in source
    assert "Failed to load. Try refreshing." in source
    assert "refresh.removeAttribute('aria-busy');" in source
