"""Replace flat category on/off toggles with per-market delivery lists

Previously each category had one boolean for individual delivery and one
for group delivery, both applying uniformly across every market allowed
by a single global telegram_alert_markets list — there was no way to say
"crypto signal alerts go to individuals and a group, forex signal alerts
go to the group only, gold gets neither" from this page; that granularity
only existed per TelegramAlertChannel (group side), never for individual
delivery or as a single place to see/set it all.

Each category/level is now its own JSON list of Asset.MARKETS values —
empty means off for every market (the inverse of TelegramAlertChannel's
own "empty markets = every market" convention, since these lists exist
specifically to be null when nothing implicit was intended). The data
migration below expands each existing boolean into the full previous
telegram_alert_markets list (or every market, if that list was empty —
matching the OLD "empty = every market" behavior it's replacing) so
routing is unchanged the moment this deploys; only False bit flips
collapse to an empty (fully off) list, same as before.

Revision ID: 654a9cfb4643
Revises: 10b11f50fdeb
Create Date: 2026-08-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '654a9cfb4643'
down_revision = '10b11f50fdeb'
branch_labels = None
depends_on = None

ALL_MARKETS = ["crypto", "forex", "gold", "silver", "indian_stock", "index"]


def upgrade():
    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('telegram_signal_individual_markets', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('telegram_signal_group_markets', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('telegram_signal_closed_individual_markets', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('telegram_signal_closed_group_markets', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('telegram_rating_change_individual_markets', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('telegram_rating_change_group_markets', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('telegram_watchlist_individual_markets', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('telegram_protective_order_individual_markets', sa.JSON(), nullable=True))

    # Must declare BOTH the old columns (read from) and the new ones
    # (written to) on the same table proxy — SQLAlchemy Core's table()
    # rejects any column referenced in .values() that wasn't declared
    # here, even though it physically exists on the table at this point
    # (added by the batch_alter_table above, not yet dropped below).
    old = sa.table(
        'platform_config',
        sa.column('id', sa.Integer()),
        sa.column('telegram_alert_markets', sa.JSON()),
        sa.column('telegram_alerts_signal', sa.Boolean()),
        sa.column('telegram_alerts_signal_group', sa.Boolean()),
        sa.column('telegram_alerts_signal_closed', sa.Boolean()),
        sa.column('telegram_alerts_signal_closed_group', sa.Boolean()),
        sa.column('telegram_alerts_rating_change', sa.Boolean()),
        sa.column('telegram_alerts_rating_change_group', sa.Boolean()),
        sa.column('telegram_alerts_watchlist', sa.Boolean()),
        sa.column('telegram_alerts_protective_order', sa.Boolean()),
        sa.column('telegram_signal_individual_markets', sa.JSON()),
        sa.column('telegram_signal_group_markets', sa.JSON()),
        sa.column('telegram_signal_closed_individual_markets', sa.JSON()),
        sa.column('telegram_signal_closed_group_markets', sa.JSON()),
        sa.column('telegram_rating_change_individual_markets', sa.JSON()),
        sa.column('telegram_rating_change_group_markets', sa.JSON()),
        sa.column('telegram_watchlist_individual_markets', sa.JSON()),
        sa.column('telegram_protective_order_individual_markets', sa.JSON()),
    )
    conn = op.get_bind()
    rows = conn.execute(sa.select(
        old.c.id, old.c.telegram_alert_markets,
        old.c.telegram_alerts_signal, old.c.telegram_alerts_signal_group,
        old.c.telegram_alerts_signal_closed, old.c.telegram_alerts_signal_closed_group,
        old.c.telegram_alerts_rating_change, old.c.telegram_alerts_rating_change_group,
        old.c.telegram_alerts_watchlist, old.c.telegram_alerts_protective_order,
    )).fetchall()

    for row in rows:
        base_markets = list(row.telegram_alert_markets) if row.telegram_alert_markets else list(ALL_MARKETS)
        conn.execute(
            old.update().where(old.c.id == row.id).values(
                telegram_signal_individual_markets=base_markets if row.telegram_alerts_signal else [],
                telegram_signal_group_markets=base_markets if row.telegram_alerts_signal_group else [],
                telegram_signal_closed_individual_markets=base_markets if row.telegram_alerts_signal_closed else [],
                telegram_signal_closed_group_markets=base_markets if row.telegram_alerts_signal_closed_group else [],
                telegram_rating_change_individual_markets=base_markets if row.telegram_alerts_rating_change else [],
                telegram_rating_change_group_markets=base_markets if row.telegram_alerts_rating_change_group else [],
                telegram_watchlist_individual_markets=base_markets if row.telegram_alerts_watchlist else [],
                telegram_protective_order_individual_markets=base_markets if row.telegram_alerts_protective_order else [],
            )
        )

    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.drop_column('telegram_alert_markets')
        batch_op.drop_column('telegram_alerts_signal')
        batch_op.drop_column('telegram_alerts_signal_group')
        batch_op.drop_column('telegram_alerts_signal_closed')
        batch_op.drop_column('telegram_alerts_signal_closed_group')
        batch_op.drop_column('telegram_alerts_rating_change')
        batch_op.drop_column('telegram_alerts_rating_change_group')
        batch_op.drop_column('telegram_alerts_watchlist')
        batch_op.drop_column('telegram_alerts_protective_order')


def downgrade():
    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('telegram_alert_markets', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('telegram_alerts_signal', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('telegram_alerts_signal_group', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('telegram_alerts_signal_closed', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('telegram_alerts_signal_closed_group', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('telegram_alerts_rating_change', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('telegram_alerts_rating_change_group', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('telegram_alerts_watchlist', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('telegram_alerts_protective_order', sa.Boolean(), nullable=False, server_default=sa.true()))

    new = sa.table(
        'platform_config',
        sa.column('id', sa.Integer()),
        sa.column('telegram_signal_individual_markets', sa.JSON()),
        sa.column('telegram_signal_group_markets', sa.JSON()),
        sa.column('telegram_signal_closed_individual_markets', sa.JSON()),
        sa.column('telegram_signal_closed_group_markets', sa.JSON()),
        sa.column('telegram_rating_change_individual_markets', sa.JSON()),
        sa.column('telegram_rating_change_group_markets', sa.JSON()),
        sa.column('telegram_watchlist_individual_markets', sa.JSON()),
        sa.column('telegram_protective_order_individual_markets', sa.JSON()),
        sa.column('telegram_alert_markets', sa.JSON()),
        sa.column('telegram_alerts_signal', sa.Boolean()),
        sa.column('telegram_alerts_signal_group', sa.Boolean()),
        sa.column('telegram_alerts_signal_closed', sa.Boolean()),
        sa.column('telegram_alerts_signal_closed_group', sa.Boolean()),
        sa.column('telegram_alerts_rating_change', sa.Boolean()),
        sa.column('telegram_alerts_rating_change_group', sa.Boolean()),
        sa.column('telegram_alerts_watchlist', sa.Boolean()),
        sa.column('telegram_alerts_protective_order', sa.Boolean()),
    )
    conn = op.get_bind()
    rows = conn.execute(sa.select(
        new.c.id,
        new.c.telegram_signal_individual_markets, new.c.telegram_signal_group_markets,
        new.c.telegram_signal_closed_individual_markets, new.c.telegram_signal_closed_group_markets,
        new.c.telegram_rating_change_individual_markets, new.c.telegram_rating_change_group_markets,
        new.c.telegram_watchlist_individual_markets, new.c.telegram_protective_order_individual_markets,
    )).fetchall()
    for row in rows:
        union = set()
        for lst in (row.telegram_signal_individual_markets, row.telegram_signal_group_markets,
                    row.telegram_signal_closed_individual_markets, row.telegram_signal_closed_group_markets,
                    row.telegram_rating_change_individual_markets, row.telegram_rating_change_group_markets,
                    row.telegram_watchlist_individual_markets, row.telegram_protective_order_individual_markets):
            union.update(lst or [])
        conn.execute(
            new.update().where(new.c.id == row.id).values(
                telegram_alert_markets=sorted(union),
                telegram_alerts_signal=bool(row.telegram_signal_individual_markets),
                telegram_alerts_signal_group=bool(row.telegram_signal_group_markets),
                telegram_alerts_signal_closed=bool(row.telegram_signal_closed_individual_markets),
                telegram_alerts_signal_closed_group=bool(row.telegram_signal_closed_group_markets),
                telegram_alerts_rating_change=bool(row.telegram_rating_change_individual_markets),
                telegram_alerts_rating_change_group=bool(row.telegram_rating_change_group_markets),
                telegram_alerts_watchlist=bool(row.telegram_watchlist_individual_markets),
                telegram_alerts_protective_order=bool(row.telegram_protective_order_individual_markets),
            )
        )

    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.drop_column('telegram_signal_individual_markets')
        batch_op.drop_column('telegram_signal_group_markets')
        batch_op.drop_column('telegram_signal_closed_individual_markets')
        batch_op.drop_column('telegram_signal_closed_group_markets')
        batch_op.drop_column('telegram_rating_change_individual_markets')
        batch_op.drop_column('telegram_rating_change_group_markets')
        batch_op.drop_column('telegram_watchlist_individual_markets')
        batch_op.drop_column('telegram_protective_order_individual_markets')
