"""add reproducibility metadata to backtests

Revision ID: 6e0f1a2b3c4d
Revises: 5d9e0f1a2b3c
Create Date: 2026-09-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "6e0f1a2b3c4d"
down_revision = "5d9e0f1a2b3c"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("backtests", schema=None) as batch_op:
        batch_op.add_column(sa.Column("engine_version", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("model_version", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("config_fingerprint", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("data_fingerprint", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("data_candles", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("backtests", schema=None) as batch_op:
        batch_op.drop_column("data_candles")
        batch_op.drop_column("data_fingerprint")
        batch_op.drop_column("config_fingerprint")
        batch_op.drop_column("model_version")
        batch_op.drop_column("engine_version")
