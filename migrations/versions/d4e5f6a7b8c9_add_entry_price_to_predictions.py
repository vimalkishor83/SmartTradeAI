"""Add entry_price to predictions (real accuracy tracking, not a proxy)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-10 21:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('predictions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('entry_price', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('predictions', schema=None) as batch_op:
        batch_op.drop_column('entry_price')
