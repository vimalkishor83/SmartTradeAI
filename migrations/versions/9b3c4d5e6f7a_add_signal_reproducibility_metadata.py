"""add reproducibility metadata to signals

Revision ID: 9b3c4d5e6f7a
Revises: 8a2b3c4d5e6f
Create Date: 2026-09-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "9b3c4d5e6f7a"
down_revision = "8a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("signals", schema=None) as batch_op:
        batch_op.add_column(sa.Column("generation_source", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("engine_version", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("model_version", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("data_fingerprint", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("data_candles", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("data_start", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("data_end", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("signals", schema=None) as batch_op:
        batch_op.drop_column("data_end")
        batch_op.drop_column("data_start")
        batch_op.drop_column("data_candles")
        batch_op.drop_column("data_fingerprint")
        batch_op.drop_column("model_version")
        batch_op.drop_column("engine_version")
        batch_op.drop_column("generation_source")
