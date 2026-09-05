"""add ensemble member outputs to predictions

Revision ID: c6f7a8b9c0d1
Revises: bd5e6f7a8b9c
Create Date: 2026-09-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c6f7a8b9c0d1"
down_revision = "bd5e6f7a8b9c"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("predictions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("model_outputs", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("predictions", schema=None) as batch_op:
        batch_op.drop_column("model_outputs")
