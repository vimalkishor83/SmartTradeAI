"""add reasoning/reasoning_detail/regime to live_read_logs

Revision ID: 2ffd33db8858
Revises: aadbad8dcb61
Create Date: 2026-09-03 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2ffd33db8858'
down_revision = 'aadbad8dcb61'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('live_read_logs', sa.Column('reasoning', sa.Text(), nullable=True))
    op.add_column('live_read_logs', sa.Column('reasoning_detail', sa.JSON(), nullable=True))
    op.add_column('live_read_logs', sa.Column('regime', sa.String(length=30), nullable=True))


def downgrade():
    op.drop_column('live_read_logs', 'regime')
    op.drop_column('live_read_logs', 'reasoning_detail')
    op.drop_column('live_read_logs', 'reasoning')
