"""persist Terminal live-read snapshots and trailing state

Revision ID: g0a1b2c3d4e5
Revises: b4c5d6e7f809
"""

from alembic import op
import sqlalchemy as sa


revision = "g0a1b2c3d4e5"
down_revision = "b4c5d6e7f809"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("live_read_logs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("trailing_stop", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("high_water_mark", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("trail_stage", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("snapshot", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("live_read_logs", schema=None) as batch_op:
        batch_op.drop_column("snapshot")
        batch_op.drop_column("trail_stage")
        batch_op.drop_column("high_water_mark")
        batch_op.drop_column("trailing_stop")
