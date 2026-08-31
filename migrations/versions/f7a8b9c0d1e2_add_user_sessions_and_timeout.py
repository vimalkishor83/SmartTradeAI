"""Add user_sessions table and platform_config.session_timeout_minutes

Gives real login-session tracking (who's logged in, from where, since
when, still active or revoked) and an admin-configurable session
timeout, backing a server-side JWT blocklist keyed on a "sid" claim
(see app/__init__.py's token_in_blocklist_loader and the login/refresh/
logout changes in app/auth/routes.py) instead of relying purely on each
token's own fixed expiry with no way to force an early logout.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-08-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f7a8b9c0d1e2'
down_revision = 'e6f7a8b9c0d1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('ip_address', sa.String(length=50), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_reason', sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('user_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_sessions_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_sessions_created_at'), ['created_at'], unique=False)

    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('session_timeout_minutes', sa.Integer(), nullable=False, server_default='1440'))


def downgrade():
    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.drop_column('session_timeout_minutes')

    with op.batch_alter_table('user_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_sessions_created_at'))
        batch_op.drop_index(batch_op.f('ix_user_sessions_user_id'))
    op.drop_table('user_sessions')
