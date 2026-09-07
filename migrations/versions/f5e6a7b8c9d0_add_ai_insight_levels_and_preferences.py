"""add AI insight entry levels and user defaults

Revision ID: f5e6a7b8c9d0
Revises: b7c8d9e0f1a2
"""

from alembic import op
import sqlalchemy as sa


revision = "f5e6a7b8c9d0"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("predictions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("entry_range_low", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("entry_range_high", sa.Float(), nullable=True))

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ai_insights_preferences", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("ai_insights_preferences")

    with op.batch_alter_table("predictions", schema=None) as batch_op:
        batch_op.drop_column("entry_range_high")
        batch_op.drop_column("entry_range_low")
