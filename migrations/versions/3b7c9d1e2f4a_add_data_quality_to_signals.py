"""add data quality snapshot to signals

Revision ID: 3b7c9d1e2f4a
Revises: e5c692b1a397
Create Date: 2026-09-05 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "3b7c9d1e2f4a"
down_revision = "e5c692b1a397"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("signals", schema=None) as batch_op:
        batch_op.add_column(sa.Column("data_quality", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("signals", schema=None) as batch_op:
        batch_op.drop_column("data_quality")
