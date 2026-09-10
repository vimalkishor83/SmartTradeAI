"""store signal and Terminal milestone history

Revision ID: i1b2c3d4e5f6
Revises: h1a2b3c4d5e6
"""

from alembic import op
import sqlalchemy as sa


revision = "i1b2c3d4e5f6"
down_revision = "h1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("signals", schema=None) as batch_op:
        batch_op.add_column(sa.Column("event_history", sa.JSON(), nullable=True))

    with op.batch_alter_table("live_read_logs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("event_history", sa.JSON(), nullable=True))

    with op.batch_alter_table("signal_history", schema=None) as batch_op:
        batch_op.add_column(sa.Column("target2", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("target3", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("event_history", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("signal_history", schema=None) as batch_op:
        batch_op.drop_column("event_history")
        batch_op.drop_column("target3")
        batch_op.drop_column("target2")

    with op.batch_alter_table("live_read_logs", schema=None) as batch_op:
        batch_op.drop_column("event_history")

    with op.batch_alter_table("signals", schema=None) as batch_op:
        batch_op.drop_column("event_history")
