"""add composite index on predictions (asset_id, timeframe, predicted_at)

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-07-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('predictions', schema=None) as batch_op:
        batch_op.create_index('idx_predictions_asset_tf_time',
                              ['asset_id', 'timeframe', 'predicted_at'], unique=False)


def downgrade():
    with op.batch_alter_table('predictions', schema=None) as batch_op:
        batch_op.drop_index('idx_predictions_asset_tf_time')
