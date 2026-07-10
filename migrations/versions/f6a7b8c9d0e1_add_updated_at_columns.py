"""Add updated_at to watchlists, watchlist_items, portfolios, portfolio_items

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-11 00:25:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('watchlists', schema=None) as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
    with op.batch_alter_table('watchlist_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
    with op.batch_alter_table('portfolios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
    with op.batch_alter_table('portfolio_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('portfolio_items', schema=None) as batch_op:
        batch_op.drop_column('updated_at')
    with op.batch_alter_table('portfolios', schema=None) as batch_op:
        batch_op.drop_column('updated_at')
    with op.batch_alter_table('watchlist_items', schema=None) as batch_op:
        batch_op.drop_column('updated_at')
    with op.batch_alter_table('watchlists', schema=None) as batch_op:
        batch_op.drop_column('updated_at')
