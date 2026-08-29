"""Add per-user telegram_bot_token_encrypted to users

Each user can now set their own Telegram bot token instead of the whole
platform sharing one TELEGRAM_BOT_TOKEN — encrypted at rest the same way
broker API credentials are (app/services/security/crypto.py).

Revision ID: c9d1e2f3a4b5
Revises: 2f5214649a5f
Create Date: 2026-08-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c9d1e2f3a4b5'
down_revision = '2f5214649a5f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('telegram_bot_token_encrypted', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('telegram_bot_token_encrypted')
