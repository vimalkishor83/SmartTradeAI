"""Add partial unique index: at most one active signal per (asset, timeframe)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-11 00:30:00.000000

"""
from alembic import op


revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    # Defensive cleanup: if any environment already has duplicate active
    # signals for the same (asset_id, timeframe) — possible from the race
    # condition this migration closes off — keep only the most recent one
    # (by generated_at) so the new unique index can actually be created.
    op.execute("""
        UPDATE signals SET status = 'expired'
        WHERE status = 'active' AND id NOT IN (
            SELECT MAX(id) FROM signals WHERE status = 'active'
            GROUP BY asset_id, timeframe
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_signals_active_asset_tf
        ON signals (asset_id, timeframe)
        WHERE status = 'active'
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_signals_active_asset_tf")
