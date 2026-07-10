"""Add approval_status column to users (self-registration approval queue)

Revision ID: a1b2c3d4e5f6
Revises: 0e70566be9f5
Create Date: 2026-07-10 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '0e70566be9f5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('approval_status', sa.String(length=20), nullable=False, server_default='approved'))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('approval_status')
