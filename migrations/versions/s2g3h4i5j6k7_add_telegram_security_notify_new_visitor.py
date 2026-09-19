"""add telegram_security_notify_new_visitor toggle to platform_config

Revision ID: s2g3h4i5j6k7
Revises: r1f2g3h4i5j6
"""

from alembic import op
import sqlalchemy as sa


revision = "s2g3h4i5j6k7"
down_revision = "r1f2g3h4i5j6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "platform_config",
        sa.Column("telegram_security_notify_new_visitor", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade():
    op.drop_column("platform_config", "telegram_security_notify_new_visitor")
