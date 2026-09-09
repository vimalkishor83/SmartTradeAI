"""add browser live-price refresh interval to platform_config

Revision ID: h1a2b3c4d5e6
Revises: g0a1b2c3d4e5
"""

from alembic import op
import sqlalchemy as sa


revision = "h1a2b3c4d5e6"
down_revision = "g0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "platform_config",
        sa.Column("live_price_refresh_interval_seconds", sa.Integer(), nullable=False, server_default="5"),
    )


def downgrade():
    op.drop_column("platform_config", "live_price_refresh_interval_seconds")
