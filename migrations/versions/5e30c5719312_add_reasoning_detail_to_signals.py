"""add reasoning_detail to signals

Revision ID: 5e30c5719312
Revises: 8226c5a96fa9
Create Date: 2026-08-16 07:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5e30c5719312'
down_revision = '8226c5a96fa9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('signals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reasoning_detail', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('signals', schema=None) as batch_op:
        batch_op.drop_column('reasoning_detail')
