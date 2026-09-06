"""add a composite index for the pending notification delivery queue

Revision ID: d7a8b9c0d1e2
Revises: c6f7a8b9c0d1
Create Date: 2026-09-06 00:00:00.000000

"""
from alembic import op


revision = "d7a8b9c0d1e2"
down_revision = "c6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.create_index(
            "idx_notif_delivery_queue",
            ["is_sent", "created_at", "id"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_index("idx_notif_delivery_queue")
