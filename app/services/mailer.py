"""Thin wrapper around Flask-Mail used by auth flows (verification, password
reset, admin signup alerts). When MAIL_SUPPRESS_SEND is on (no SMTP creds
configured — see app/config.py), Flask-Mail silently no-ops the send, so we
log the message instead — keeps every flow fully testable before real SMTP
credentials exist."""
import logging
from flask import current_app
from flask_mail import Message
from app.extensions import mail

logger = logging.getLogger(__name__)


def send_email(to, subject, body):
    try:
        msg = Message(subject=subject, recipients=[to], body=body)
        mail.send(msg)
        if current_app.config.get("MAIL_SUPPRESS_SEND"):
            logger.info(f"[mailer] SMTP not configured — email suppressed. To: {to} | Subject: {subject}\n{body}")
        return True
    except Exception as e:
        logger.error(f"[mailer] Failed to send email to {to}: {e}")
        return False


def send_verification_email(user, token):
    url = f"{current_app.config['FRONTEND_URL']}/verify-email?token={token}"
    send_email(
        user.email,
        "Verify your SmartTrade AI account",
        f"Hi {user.username},\n\n"
        f"Please verify your email address to activate your account:\n{url}\n\n"
        f"This link expires in 24 hours. If you didn't create this account, ignore this email.",
    )


def send_password_reset_email(user, token):
    url = f"{current_app.config['FRONTEND_URL']}/reset-password?token={token}"
    send_email(
        user.email,
        "Reset your SmartTrade AI password",
        f"Hi {user.username},\n\n"
        f"Click the link below to reset your password:\n{url}\n\n"
        f"This link expires in 1 hour. If you didn't request this, ignore this email — "
        f"your password will not be changed.",
    )


def send_admin_new_signup_alert(admin_emails, user):
    if not admin_emails:
        return
    for email in admin_emails:
        send_email(
            email,
            "New SmartTrade AI signup pending approval",
            f"A new user just registered and is awaiting approval:\n\n"
            f"Username: {user.username}\nEmail: {user.email}\n"
            f"Registered: {user.created_at.isoformat()}\n\n"
            f"Review in Admin > Users.",
        )
