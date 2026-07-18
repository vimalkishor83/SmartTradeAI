"""add lane_verdicts/invalidation_conditions/target_allocations to signals

Revision ID: 7b2f4a91c3d6
Revises: 45cdcf9eb85e
Create Date: 2026-07-18 20:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7b2f4a91c3d6'
down_revision = '45cdcf9eb85e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('signals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lane_verdicts', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('invalidation_conditions', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('target_allocations', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('signals', schema=None) as batch_op:
        batch_op.drop_column('target_allocations')
        batch_op.drop_column('invalidation_conditions')
        batch_op.drop_column('lane_verdicts')
