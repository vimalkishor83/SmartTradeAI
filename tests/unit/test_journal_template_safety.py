"""Contract checks for Journal rendering and mutation controls."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "journal.html"


def test_journal_uses_delegated_entry_actions():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert 'data-edit-entry="${id}"' in source
    assert 'data-delete-entry="${id}"' in source
    assert "journalBody').addEventListener('click'" in source


def test_journal_escapes_provider_and_user_values():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "function _journalHtml(value)" in source
    assert "function _journalId(value)" in source
    assert "_journalHtml(_journalText(e.asset_symbol, '—'))" in source
    assert "_journalHtml(_journalTitle(best[0]))" in source
    assert 'maxlength="5000"' in source


def test_journal_edit_delete_and_save_paths_are_safe():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "API.get(`/journal/${id}`)" in source
    assert "if (await API.delete(`/journal/${id}`))" in source
    assert "let _saveTradeInFlight = false;" in source
    assert "if (_saveTradeInFlight) return;" in source
    assert "journal_weekly_notes_' + (userId || 'account')" in source


def test_journal_controls_have_accessible_relationships_and_status():
    source = TEMPLATE.read_text(encoding="utf-8")

    for field in [
        "fDate", "fAsset", "fMarket", "fDirection", "fTimeframe", "fEntry",
        "fExit", "fQty", "fSL", "fTarget", "fEmotion", "fSetupTags", "fNotes",
    ]:
        assert f'for="{field}"' in source
    assert '<caption class="visually-hidden">Trade journal entries</caption>' in source
    assert 'id="journalStatus" role="status" aria-live="polite"' in source
    assert 'aria-label="Edit journal entry"' in source
    assert 'aria-label="Delete journal entry"' in source
    assert "function _journalStatus(message)" in source
