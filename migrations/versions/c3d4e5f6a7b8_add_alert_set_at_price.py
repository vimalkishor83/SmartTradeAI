"""Add alert_set_at_price to watchlist_items (fixes alert-crossing bug)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-10 21:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('watchlist_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('alert_set_at_price', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('watchlist_items', schema=None) as batch_op:
        batch_op.drop_column('alert_set_at_price')
