"""Add referral_codes table and broker_id/referral_code_id on users

Revision ID: 57b53ddaef6c
Revises: d2e3f4a5b6c7
Create Date: 2026-08-15 04:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '57b53ddaef6c'
down_revision = 'd2e3f4a5b6c7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'referral_codes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(length=40), nullable=False),
        sa.Column('broker_name', sa.String(length=80), nullable=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('referred_role_id', sa.Integer(), sa.ForeignKey('roles.id'), nullable=True),
        sa.Column('referred_subscription_id', sa.Integer(), sa.ForeignKey('subscriptions.id'), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('max_uses', sa.Integer(), nullable=True),
        sa.Column('uses_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_referral_codes_code', 'referral_codes', ['code'], unique=True)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('broker_id', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('referral_code_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_users_referral_code_id', 'referral_codes', ['referral_code_id'], ['id']
        )


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('fk_users_referral_code_id', type_='foreignkey')
        batch_op.drop_column('referral_code_id')
        batch_op.drop_column('broker_id')

    op.drop_index('ix_referral_codes_code', table_name='referral_codes')
    op.drop_table('referral_codes')
