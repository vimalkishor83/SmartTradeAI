"""Add missing indexes on backtests, predictions, news for hot query paths

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-11 00:15:00.000000

"""
from alembic import op


revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('backtests', schema=None) as batch_op:
        batch_op.create_index('ix_backtests_user_id', ['user_id'], unique=False)
        batch_op.create_index('ix_backtests_created_at', ['created_at'], unique=False)

    with op.batch_alter_table('predictions', schema=None) as batch_op:
        batch_op.create_index('ix_predictions_asset_id', ['asset_id'], unique=False)
        batch_op.create_index('ix_predictions_timeframe', ['timeframe'], unique=False)

    with op.batch_alter_table('news', schema=None) as batch_op:
        batch_op.create_index('ix_news_published_at', ['published_at'], unique=False)


def downgrade():
    with op.batch_alter_table('news', schema=None) as batch_op:
        batch_op.drop_index('ix_news_published_at')

    with op.batch_alter_table('predictions', schema=None) as batch_op:
        batch_op.drop_index('ix_predictions_timeframe')
        batch_op.drop_index('ix_predictions_asset_id')

    with op.batch_alter_table('backtests', schema=None) as batch_op:
        batch_op.drop_index('ix_backtests_created_at')
        batch_op.drop_index('ix_backtests_user_id')
