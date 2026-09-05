"""add data quality metadata to predictions

Revision ID: bd5e6f7a8b9c
Revises: ac4d5e6f7a8b
Create Date: 2026-09-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "bd5e6f7a8b9c"
down_revision = "ac4d5e6f7a8b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("predictions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("data_quality", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("predictions", schema=None) as batch_op:
        batch_op.drop_column("data_quality")
