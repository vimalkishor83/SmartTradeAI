"""Add per-category Telegram alert toggles and rating_snapshots table

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-08-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('telegram_alert_markets', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('telegram_alerts_signal', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('telegram_alerts_signal_closed', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('telegram_alerts_watchlist', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('telegram_alerts_protective_order', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('telegram_alerts_rating_change', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('telegram_rating_change_sensitivity', sa.String(length=20), nullable=False, server_default='cross_zone'))

    op.create_table(
        'rating_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('asset_id', sa.Integer(), nullable=False),
        sa.Column('timeframe', sa.String(length=10), nullable=False),
        sa.Column('rating', sa.String(length=20), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('asset_id', 'timeframe', name='uq_rating_snapshot_asset_tf'),
    )
    with op.batch_alter_table('rating_snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rating_snapshots_asset_id'), ['asset_id'], unique=False)


def downgrade():
    with op.batch_alter_table('rating_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_rating_snapshots_asset_id'))
    op.drop_table('rating_snapshots')

    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.drop_column('telegram_rating_change_sensitivity')
        batch_op.drop_column('telegram_alerts_rating_change')
        batch_op.drop_column('telegram_alerts_protective_order')
        batch_op.drop_column('telegram_alerts_watchlist')
        batch_op.drop_column('telegram_alerts_signal_closed')
        batch_op.drop_column('telegram_alerts_signal')
        batch_op.drop_column('telegram_alert_markets')
