"""Add passphrase_encrypted to user_broker_credentials (multi-broker support)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-11 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_broker_credentials', schema=None) as batch_op:
        batch_op.add_column(sa.Column('passphrase_encrypted', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('user_broker_credentials', schema=None) as batch_op:
        batch_op.drop_column('passphrase_encrypted')
