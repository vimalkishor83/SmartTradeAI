"""add spread assumptions and costs to backtests

Revision ID: 7f1a2b3c4d5e
Revises: 6e0f1a2b3c4d
Create Date: 2026-09-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "7f1a2b3c4d5e"
down_revision = "6e0f1a2b3c4d"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("backtests", schema=None) as batch_op:
        batch_op.add_column(sa.Column("total_spread", sa.Float(), nullable=True, server_default="0"))
        batch_op.add_column(sa.Column("spread_pct", sa.Float(), nullable=True, server_default="0"))


def downgrade():
    with op.batch_alter_table("backtests", schema=None) as batch_op:
        batch_op.drop_column("spread_pct")
        batch_op.drop_column("total_spread")
