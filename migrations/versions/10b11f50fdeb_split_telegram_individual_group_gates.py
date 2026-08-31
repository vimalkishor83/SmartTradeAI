"""Split each Telegram category's single toggle into individual + group gates

Previously telegram_alerts_signal (etc.) gated BOTH each subscriber's
personal alert AND whether any TelegramAlertChannel could receive that
category at all — there was no way to run a category to individuals
only, groups only, both, or neither. Adds a matching "_group" column per
category (signal, signal_closed, rating_change — watchlist and
protective_order stay individual-only, they're about one subscriber's
own item/position) and copies each existing column's current value into
its new "_group" counterpart, so live alert routing is unchanged the
moment this deploys; the admin can then split them apart from the
Telegram Alerts page.

Revision ID: 10b11f50fdeb
Revises: f7a8b9c0d1e2
Create Date: 2026-08-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '10b11f50fdeb'
down_revision = 'f7a8b9c0d1e2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('telegram_alerts_signal_group', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('telegram_alerts_signal_closed_group', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('telegram_alerts_rating_change_group', sa.Boolean(), nullable=False, server_default=sa.false()))

    # Preserve current live behavior exactly for the existing row(s) —
    # whatever an admin already had each single toggle set to keeps
    # working the same way for group delivery too, rather than silently
    # resetting group delivery to a fresh-install default.
    platform_config = sa.table(
        'platform_config',
        sa.column('telegram_alerts_signal', sa.Boolean()),
        sa.column('telegram_alerts_signal_group', sa.Boolean()),
        sa.column('telegram_alerts_signal_closed', sa.Boolean()),
        sa.column('telegram_alerts_signal_closed_group', sa.Boolean()),
        sa.column('telegram_alerts_rating_change', sa.Boolean()),
        sa.column('telegram_alerts_rating_change_group', sa.Boolean()),
    )
    conn = op.get_bind()
    conn.execute(platform_config.update().values(
        telegram_alerts_signal_group=platform_config.c.telegram_alerts_signal,
        telegram_alerts_signal_closed_group=platform_config.c.telegram_alerts_signal_closed,
        telegram_alerts_rating_change_group=platform_config.c.telegram_alerts_rating_change,
    ))


def downgrade():
    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.drop_column('telegram_alerts_rating_change_group')
        batch_op.drop_column('telegram_alerts_signal_closed_group')
        batch_op.drop_column('telegram_alerts_signal_group')
