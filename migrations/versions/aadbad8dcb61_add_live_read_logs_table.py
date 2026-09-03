"""add live_read_logs table

Revision ID: aadbad8dcb61
Revises: e153080c311c
Create Date: 2026-09-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'aadbad8dcb61'
down_revision = 'e153080c311c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'live_read_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('asset_id', sa.Integer(), nullable=False),
        sa.Column('timeframe', sa.String(length=10), nullable=False),
        sa.Column('signal_type', sa.String(length=10), nullable=False),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('entry_price', sa.Float(), nullable=False),
        sa.Column('stop_loss', sa.Float(), nullable=True),
        sa.Column('target1', sa.Float(), nullable=True),
        sa.Column('target2', sa.Float(), nullable=True),
        sa.Column('target3', sa.Float(), nullable=True),
        sa.Column('outcome', sa.String(length=10), nullable=True),
        sa.Column('exit_price', sa.Float(), nullable=True),
        sa.Column('generated_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_live_read_logs_asset_id'), 'live_read_logs', ['asset_id'], unique=False)
    op.create_index(op.f('ix_live_read_logs_timeframe'), 'live_read_logs', ['timeframe'], unique=False)
    op.create_index(op.f('ix_live_read_logs_generated_at'), 'live_read_logs', ['generated_at'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_live_read_logs_generated_at'), table_name='live_read_logs')
    op.drop_index(op.f('ix_live_read_logs_timeframe'), table_name='live_read_logs')
    op.drop_index(op.f('ix_live_read_logs_asset_id'), table_name='live_read_logs')
    op.drop_table('live_read_logs')
