"""Regression coverage for incomplete protective-order rows."""

from datetime import datetime, timezone

from app.models.protective_order import ProtectiveOrder


def test_protective_order_to_dict_tolerates_missing_created_at():
    order = ProtectiveOrder(created_at=None)

    assert order.to_dict()["created_at"] is None


def test_protective_order_to_dict_preserves_timestamp_format():
    created_at = datetime(2026, 9, 6, 10, 30, tzinfo=timezone.utc)
    order = ProtectiveOrder(created_at=created_at)

    assert order.to_dict()["created_at"] == created_at.isoformat()
