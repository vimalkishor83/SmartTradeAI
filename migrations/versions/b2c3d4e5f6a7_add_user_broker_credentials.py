"""Add user_broker_credentials table (per-user broker API keys)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-10 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_broker_credentials',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('api_key_encrypted', sa.Text(), nullable=True),
        sa.Column('api_secret_encrypted', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('connection_status', sa.String(length=20), nullable=True),
        sa.Column('last_sync', sa.DateTime(), nullable=True),
        sa.Column('last_latency_ms', sa.Integer(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'provider', name='uq_user_broker_provider'),
    )
    with op.batch_alter_table('user_broker_credentials', schema=None) as batch_op:
        batch_op.create_index('ix_user_broker_credentials_user_id', ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('user_broker_credentials', schema=None) as batch_op:
        batch_op.drop_index('ix_user_broker_credentials_user_id')
    op.drop_table('user_broker_credentials')
