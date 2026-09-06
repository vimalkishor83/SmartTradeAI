"""Regression coverage for legacy journal timestamps."""

from datetime import date, datetime, timezone

from app.models.journal import JournalEntry


def test_journal_entry_tolerates_null_created_at():
    entry = JournalEntry(trade_date=date(2026, 9, 6), created_at=None)

    assert entry.to_dict()["created_at"] is None


def test_journal_entry_serializes_created_at_as_isoformat():
    created_at = datetime(2026, 9, 6, 10, 30, tzinfo=timezone.utc)
    entry = JournalEntry(trade_date=date(2026, 9, 6), created_at=created_at)

    assert entry.to_dict()["created_at"] == created_at.isoformat()
