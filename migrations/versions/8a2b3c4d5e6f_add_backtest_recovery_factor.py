"""add recovery factor to backtests

Revision ID: 8a2b3c4d5e6f
Revises: 7f1a2b3c4d5e
Create Date: 2026-09-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "8a2b3c4d5e6f"
down_revision = "7f1a2b3c4d5e"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("backtests", schema=None) as batch_op:
        batch_op.add_column(sa.Column("recovery_factor", sa.Float(), nullable=True, server_default="0"))


def downgrade():
    with op.batch_alter_table("backtests", schema=None) as batch_op:
        batch_op.drop_column("recovery_factor")
