"""Add timeframes to telegram_alert_channels

Lets a channel scope itself to specific timeframes too, not just markets
— e.g. a "Scalpers" channel watching only 1m/5m signals alongside a
"Swing" channel watching only 4h/1d/1w, out of the same market/category
setup. Empty list (the default) means every timeframe, same convention
as the existing markets column.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-08-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e6f7a8b9c0d1'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('telegram_alert_channels', schema=None) as batch_op:
        batch_op.add_column(sa.Column('timeframes', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('telegram_alert_channels', schema=None) as batch_op:
        batch_op.drop_column('timeframes')
