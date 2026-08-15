"""add advanced_charts_enabled and broker_connect_enabled to subscriptions

Revision ID: 8226c5a96fa9
Revises: d07e8fbd6e1c
Create Date: 2026-08-15 18:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8226c5a96fa9'
down_revision = 'd07e8fbd6e1c'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('advanced_charts_enabled', sa.Boolean(), nullable=True, server_default=sa.false()))
        batch_op.add_column(sa.Column('broker_connect_enabled', sa.Boolean(), nullable=True, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.drop_column('broker_connect_enabled')
        batch_op.drop_column('advanced_charts_enabled')
