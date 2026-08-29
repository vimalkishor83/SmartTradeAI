"""Add is_super_admin column to users (admin write-access split)

Revision ID: f1a2b3c4d5e6
Revises: c9d1e2f3a4b5
Create Date: 2026-08-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f1a2b3c4d5e6'
down_revision = 'c9d1e2f3a4b5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_super_admin', sa.Boolean(), nullable=False, server_default=sa.false()))

    # Every account that already held the "admin" role had full read/write
    # access to everything before this migration — that's the only kind of
    # admin that existed. Defaulting the new column to False for everyone
    # (including them) would silently downgrade every existing admin to
    # view-only on their next request. Promote them to super admin here so
    # nobody already trusted with full access loses it; is_super_admin only
    # matters as a deliberate, narrower grant for admins created from here on.
    # TRUE (not 1) — SQLite treats it as 1, but Postgres' boolean column
    # rejects a bare integer literal with no implicit cast; TRUE/FALSE are
    # valid boolean literals on both.
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE users SET is_super_admin = TRUE WHERE role_id IN "
        "(SELECT id FROM roles WHERE name = 'admin')"
    ))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('is_super_admin')
