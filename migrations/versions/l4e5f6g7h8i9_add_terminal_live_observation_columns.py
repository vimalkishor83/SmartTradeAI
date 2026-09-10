"""store the latest Terminal live-read observation

Revision ID: l4e5f6g7h8i9
Revises: k3d4e5f6g7h8
"""

from alembic import op
import sqlalchemy as sa


revision = "l4e5f6g7h8i9"
down_revision = "k3d4e5f6g7h8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("live_read_logs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("current_price", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("last_observed_at", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_live_read_logs_last_observed_at", ["last_observed_at"], unique=False)


def downgrade():
    with op.batch_alter_table("live_read_logs", schema=None) as batch_op:
        batch_op.drop_index("ix_live_read_logs_last_observed_at")
        batch_op.drop_column("last_observed_at")
        batch_op.drop_column("current_price")
