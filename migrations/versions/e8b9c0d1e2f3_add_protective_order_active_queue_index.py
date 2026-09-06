"""add a composite index for the active protective-order monitor queue

Revision ID: e8b9c0d1e2f3
Revises: d7a8b9c0d1e2
Create Date: 2026-09-06 00:00:00.000000

"""
from alembic import op


revision = "e8b9c0d1e2f3"
down_revision = "d7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("protective_orders", schema=None) as batch_op:
        batch_op.create_index(
            "idx_protective_order_active_queue",
            ["status", "asset_id", "id"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("protective_orders", schema=None) as batch_op:
        batch_op.drop_index("idx_protective_order_active_queue")
