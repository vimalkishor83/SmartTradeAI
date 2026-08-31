"""Add telegram_group_chat_id to platform_config

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-08-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b3c4d5e6f7a8'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('telegram_group_chat_id', sa.String(length=64), nullable=True))


def downgrade():
    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.drop_column('telegram_group_chat_id')
