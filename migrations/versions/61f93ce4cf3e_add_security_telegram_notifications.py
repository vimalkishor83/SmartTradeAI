"""Add dedicated security-alerts Telegram chat + per-event toggles

telegram_security_chat_id: a Telegram group/chat id, separate from any
trading-signal TelegramAlertChannel and from a super admin's own
personal alerts, dedicated to security notifications only. Uses the
shared platform bot (TELEGRAM_BOT_TOKEN) via _send_to_chat, same as the
existing signal group channels.

telegram_security_notify_login_success: every successful login, not
just new-IP ones. Off by default — high volume on an active site.

telegram_security_notify_login_failed: failed login attempts (wrong
password / unknown account). On by default — a low-volume, genuinely
actionable security signal.

telegram_security_notify_new_ip_login: broadcasts the existing new-IP-
login event (see telegram_alerts_new_ip_login / send_new_ip_login_alert)
to this group too, independent of whether it's also going to admins'
personal DMs. On by default.

telegram_security_notify_admin_unauthorized: someone hits an /admin/*
page without a valid session or without the admin role. On by default.

telegram_security_notify_anonymous_visits: every anonymous page view
of a public route. Off by default — this is opt-in, high-volume, and
exists because the admin explicitly asked for the option even knowing
the volume tradeoff.

Revision ID: 61f93ce4cf3e
Revises: 9511c774bf49
Create Date: 2026-09-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '61f93ce4cf3e'
down_revision = '9511c774bf49'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('telegram_security_chat_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('telegram_security_notify_login_success', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('telegram_security_notify_login_failed', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('telegram_security_notify_new_ip_login', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('telegram_security_notify_admin_unauthorized', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('telegram_security_notify_anonymous_visits', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.drop_column('telegram_security_notify_anonymous_visits')
        batch_op.drop_column('telegram_security_notify_admin_unauthorized')
        batch_op.drop_column('telegram_security_notify_new_ip_login')
        batch_op.drop_column('telegram_security_notify_login_failed')
        batch_op.drop_column('telegram_security_notify_login_success')
        batch_op.drop_column('telegram_security_chat_id')
