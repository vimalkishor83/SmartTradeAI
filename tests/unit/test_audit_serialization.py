"""Regression coverage for legacy audit and system log timestamps."""

from datetime import datetime, timezone

from app.models.audit import AuditLog, SystemLog


def test_audit_and_system_log_tolerate_null_created_at():
    audit = AuditLog(action="order_rejected", created_at=None)
    system = SystemLog(level="ERROR", message="provider unavailable", created_at=None)

    assert audit.to_dict()["created_at"] is None
    assert system.to_dict()["created_at"] is None


def test_audit_and_system_log_serialize_created_at_as_isoformat():
    created_at = datetime(2026, 9, 6, 10, 30, tzinfo=timezone.utc)
    audit = AuditLog(action="order_placed", created_at=created_at)
    system = SystemLog(level="INFO", message="healthy", created_at=created_at)

    assert audit.to_dict()["created_at"] == created_at.isoformat()
    assert system.to_dict()["created_at"] == created_at.isoformat()
