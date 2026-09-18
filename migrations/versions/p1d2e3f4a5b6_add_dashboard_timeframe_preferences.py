"""add per-user dashboard timeframe preferences

Revision ID: p1d2e3f4a5b6
Revises: n8b9c0d1e2f3
"""

from alembic import op
import sqlalchemy as sa


revision = "p1d2e3f4a5b6"
down_revision = "n8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("dashboard_preferences", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("dashboard_preferences")
