"""Regression coverage for stable provider-log retrieval."""

from pathlib import Path

from app.models.api_config import APILog


def test_api_log_declares_created_timestamp_tiebreaker_index():
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in APILog.__table__.indexes
    }

    assert indexes["idx_api_logs_config_time_id"] == (
        "api_config_id", "created_at", "id",
    )


def test_admin_api_log_feed_orders_equal_timestamps_by_id():
    source = (
        Path(__file__).parents[2] / "app" / "api" / "v1" / "admin.py"
    ).read_text(encoding="utf-8")

    assert ".order_by(APILog.created_at.desc(), APILog.id.desc())" in source
