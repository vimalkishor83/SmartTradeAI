"""add data quality snapshot to live read logs

Revision ID: 4c8d9e0f1a2b
Revises: 3b7c9d1e2f4a
Create Date: 2026-09-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "4c8d9e0f1a2b"
down_revision = "3b7c9d1e2f4a"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("live_read_logs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("data_quality", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("live_read_logs", schema=None) as batch_op:
        batch_op.drop_column("data_quality")
