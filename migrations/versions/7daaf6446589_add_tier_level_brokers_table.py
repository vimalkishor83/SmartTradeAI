"""Add subscriptions.tier_level, brokers table, users.broker_id/broker_account_id

Revision ID: 7daaf6446589
Revises: 57b53ddaef6c
Create Date: 2026-08-15 05:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '7daaf6446589'
down_revision = '57b53ddaef6c'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tier_level', sa.Integer(), nullable=False, server_default='0'))

    op.create_table(
        'brokers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('referral_link', sa.String(length=500), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_brokers_name', 'brokers', ['name'], unique=True)

    with op.batch_alter_table('users', schema=None) as batch_op:
        # Earlier migration (57b53ddaef6c) added users.broker_id as a plain
        # String — replaced here with a proper FK to brokers, plus a
        # separate free-text column for the user's own account/client ID.
        batch_op.drop_column('broker_id')
        batch_op.add_column(sa.Column('broker_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('broker_account_id', sa.String(length=80), nullable=True))
        batch_op.create_foreign_key('fk_users_broker_id', 'brokers', ['broker_id'], ['id'])


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('fk_users_broker_id', type_='foreignkey')
        batch_op.drop_column('broker_account_id')
        batch_op.drop_column('broker_id')
        batch_op.add_column(sa.Column('broker_id', sa.String(length=80), nullable=True))

    op.drop_index('ix_brokers_name', table_name='brokers')
    op.drop_table('brokers')

    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.drop_column('tier_level')
