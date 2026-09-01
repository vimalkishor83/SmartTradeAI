"""Add telegram_alerts_new_ip_login and audit_log_super_admins toggles

telegram_alerts_new_ip_login: security notification (not a trading
alert, no market/individual-group split applies) — sent to every super
admin's own personal Telegram chat the moment a login uses an IP not
seen for that account before. Default True since this is a security
feature an admin should have to deliberately turn off, not opt into.

audit_log_super_admins: off by default — a super admin's own logins/
actions don't get written to the audit trail unless deliberately turned
on. Enforced in AuditLog.record(), the single entry point every audit
call site now goes through instead of constructing AuditLog(...) rows
directly.

Revision ID: e153080c311c
Revises: 654a9cfb4643
Create Date: 2026-09-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e153080c311c'
down_revision = '654a9cfb4643'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('telegram_alerts_new_ip_login', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('audit_log_super_admins', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.drop_column('audit_log_super_admins')
        batch_op.drop_column('telegram_alerts_new_ip_login')
