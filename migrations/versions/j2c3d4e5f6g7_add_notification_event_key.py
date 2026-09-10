"""add notification event idempotency key

Revision ID: j2c3d4e5f6g7
Revises: i1b2c3d4e5f6
"""

from alembic import op
import sqlalchemy as sa


revision = "j2c3d4e5f6g7"
down_revision = "i1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("notification_key", sa.String(length=180), nullable=True))

    op.create_index(
        "uq_notif_user_key",
        "notifications",
        ["user_id", "notification_key"],
        unique=True,
    )


def downgrade():
    op.drop_index("uq_notif_user_key", table_name="notifications")
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_column("notification_key")
