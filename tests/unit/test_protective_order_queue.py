"""Regression coverage for the protective-order monitor query contract."""

from app.models.protective_order import ProtectiveOrder


def test_protective_order_declares_active_queue_index():
    indexes = {index.name: tuple(column.name for column in index.columns)
               for index in ProtectiveOrder.__table__.indexes}

    assert indexes["idx_protective_order_active_queue"] == ("status", "asset_id", "id")


def test_protective_order_worker_uses_stable_active_order():
    from pathlib import Path

    source = (Path(__file__).parents[2] / "app" / "tasks" / "protective_order_tasks.py").read_text(encoding="utf-8")

    assert '.filter_by(status="active")' in source
    assert ".order_by(ProtectiveOrder.asset_id.asc(), ProtectiveOrder.id.asc())" in source
