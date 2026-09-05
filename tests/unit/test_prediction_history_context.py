"""Tests for the bounded historical context shown with AI predictions."""
from types import SimpleNamespace

from app.api.v1.predictions import _prediction_history_summary


def test_prediction_history_summary_reports_accuracy_and_sample_size():
    rows = [
        SimpleNamespace(was_correct=True),
        SimpleNamespace(was_correct=True),
        SimpleNamespace(was_correct=False),
    ]

    assert _prediction_history_summary(rows) == {
        "sample_size": 3,
        "correct": 2,
        "accuracy": 66.7,
        "scope": "same asset and timeframe, recent resolved predictions",
    }


def test_prediction_history_summary_is_explicit_when_no_prediction_is_resolved():
    summary = _prediction_history_summary([])

    assert summary["sample_size"] == 0
    assert summary["correct"] == 0
    assert summary["accuracy"] is None
