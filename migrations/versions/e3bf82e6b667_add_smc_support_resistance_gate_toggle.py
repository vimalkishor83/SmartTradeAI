"""add smc_support_resistance_gate_enabled to platform_config

Revision ID: e3bf82e6b667
Revises: 4292c1f1c479
Create Date: 2026-09-04 03:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e3bf82e6b667'
down_revision = '4292c1f1c479'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'platform_config',
        sa.Column('smc_support_resistance_gate_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column('platform_config', 'smc_support_resistance_gate_enabled')
