"""add composite index on journal_entries (user_id, trade_date)

Revision ID: c1d2e3f4a5b6
Revises: 7b2f4a91c3d6
Create Date: 2026-07-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1d2e3f4a5b6'
down_revision = '7b2f4a91c3d6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('journal_entries', schema=None) as batch_op:
        batch_op.create_index('idx_journal_user_trade_date', ['user_id', 'trade_date'], unique=False)


def downgrade():
    with op.batch_alter_table('journal_entries', schema=None) as batch_op:
        batch_op.drop_index('idx_journal_user_trade_date')
