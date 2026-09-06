"""Regression coverage for legacy backtest timestamps."""

from datetime import datetime, timezone

from app.models.backtest import Backtest


def test_backtest_to_dict_tolerates_null_created_at():
    backtest = Backtest(created_at=None)

    assert backtest.to_dict()["created_at"] is None


def test_backtest_to_dict_serializes_created_at_as_isoformat():
    created_at = datetime(2026, 9, 6, 10, 30, tzinfo=timezone.utc)
    backtest = Backtest(created_at=created_at)

    assert backtest.to_dict()["created_at"] == created_at.isoformat()
