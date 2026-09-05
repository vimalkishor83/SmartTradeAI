"""add model version metadata to predictions

Revision ID: ac4d5e6f7a8b
Revises: 9b3c4d5e6f7a
Create Date: 2026-09-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "ac4d5e6f7a8b"
down_revision = "9b3c4d5e6f7a"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("predictions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("model_version", sa.String(length=50), nullable=True))


def downgrade():
    with op.batch_alter_table("predictions", schema=None) as batch_op:
        batch_op.drop_column("model_version")
