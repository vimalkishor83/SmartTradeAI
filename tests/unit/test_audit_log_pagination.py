"""Regression coverage for stable, indexed audit-log pagination."""

from pathlib import Path

from app.models.audit import AuditLog


def test_audit_log_declares_created_timestamp_tiebreaker_index():
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in AuditLog.__table__.indexes
    }

    assert indexes["idx_audit_logs_created_id"] == ("created_at", "id")


def test_admin_audit_feed_orders_equal_timestamps_by_id():
    source = (
        Path(__file__).parents[2] / "app" / "api" / "v1" / "admin.py"
    ).read_text(encoding="utf-8")

    assert ".order_by(AuditLog.created_at.desc(), AuditLog.id.desc())" in source
