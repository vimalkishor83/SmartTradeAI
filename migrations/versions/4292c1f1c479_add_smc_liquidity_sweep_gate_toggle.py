"""add smc_liquidity_sweep_gate_enabled to platform_config

Revision ID: 4292c1f1c479
Revises: 72f6d2c96dc8
Create Date: 2026-09-04 02:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4292c1f1c479'
down_revision = '72f6d2c96dc8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'platform_config',
        sa.Column('smc_liquidity_sweep_gate_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column('platform_config', 'smc_liquidity_sweep_gate_enabled')
