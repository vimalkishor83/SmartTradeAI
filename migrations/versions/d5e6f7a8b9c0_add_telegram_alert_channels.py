"""Replace single Telegram group with multi-channel telegram_alert_channels

Different markets legitimately want different Telegram audiences and
different alert mixes — one crypto group, one forex/stocks group, each
with its own category toggles — instead of a single global group that
gets every alert for every market. Drops the single
platform_config.telegram_group_chat_id column (unused — never set in
production) in favor of the new telegram_alert_channels table.

Channels only carry alerts_signal / alerts_signal_closed /
alerts_rating_change — watchlist and protective-order alerts are about
one specific user's own watchlist item or open position, so they only
ever make sense as individual DMs (PlatformConfig's
telegram_alerts_watchlist / telegram_alerts_protective_order), never a
public/group broadcast.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-08-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'telegram_alert_channels',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('group_chat_id', sa.String(length=64), nullable=False),
        sa.Column('markets', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('alerts_signal', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('alerts_signal_closed', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('alerts_rating_change', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('rating_change_sensitivity', sa.String(length=20), nullable=False, server_default='cross_zone'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.drop_column('telegram_group_chat_id')


def downgrade():
    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('telegram_group_chat_id', sa.String(length=64), nullable=True))

    op.drop_table('telegram_alert_channels')
