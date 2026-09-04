"""add terminal_default_timeframe to platform_config

Revision ID: 9511c774bf49
Revises: e3bf82e6b667
Create Date: 2026-09-04 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9511c774bf49'
down_revision = 'e3bf82e6b667'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'platform_config',
        sa.Column('terminal_default_timeframe', sa.String(length=10), nullable=False, server_default='1h'),
    )


def downgrade():
    op.drop_column('platform_config', 'terminal_default_timeframe')
