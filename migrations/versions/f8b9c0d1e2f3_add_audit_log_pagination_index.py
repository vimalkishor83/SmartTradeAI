"""add deterministic audit log pagination index

Revision ID: f8b9c0d1e2f3
Revises: e8b9c0d1e2f3
Create Date: 2026-09-06 00:00:00.000000

"""
from alembic import op


revision = "f8b9c0d1e2f3"
down_revision = "e8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.create_index(
            "idx_audit_logs_created_id",
            ["created_at", "id"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.drop_index("idx_audit_logs_created_id")
