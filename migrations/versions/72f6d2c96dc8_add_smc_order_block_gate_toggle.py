"""add smc_order_block_gate_enabled to platform_config

Revision ID: 72f6d2c96dc8
Revises: 2ffd33db8858
Create Date: 2026-09-04 02:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '72f6d2c96dc8'
down_revision = '2ffd33db8858'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'platform_config',
        sa.Column('smc_order_block_gate_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column('platform_config', 'smc_order_block_gate_enabled')
