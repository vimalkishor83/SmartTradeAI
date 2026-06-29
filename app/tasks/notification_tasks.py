"""Background jobs for sending notifications."""
import logging

logger = logging.getLogger(__name__)


def send_pending_notifications(app):
    with app.app_context():
        from app.models.notification import Notification
        from app.models.user import User
        from app.extensions import db
        from datetime import datetime

        pending = Notification.query.filter_by(is_sent=False).limit(50).all()
        for notif in pending:
            user = User.query.get(notif.user_id)
            if not user:
                continue
            try:
                if user.email_notifications and notif.channel in ("email", None):
                    _send_email(user.email, notif.title, notif.message)
                if user.telegram_enabled and user.telegram_chat_id:
                    _send_telegram(user.telegram_chat_id, f"*{notif.title}*\n{notif.message}")
                notif.is_sent = True
                notif.sent_at = datetime.utcnow()
            except Exception as e:
                logger.error(f"Notification send failed: {e}")

        db.session.commit()


def _send_email(to_email: str, subject: str, body: str):
    try:
        import smtplib
        from email.mime.text import MIMEText
        from flask import current_app

        msg = MIMEText(body, "html")
        msg["Subject"] = subject
        msg["From"] = current_app.config.get("MAIL_DEFAULT_SENDER")
        msg["To"] = to_email

        server = smtplib.SMTP(
            current_app.config.get("MAIL_SERVER", "smtp.gmail.com"),
            current_app.config.get("MAIL_PORT", 587),
        )
        server.starttls()
        server.login(
            current_app.config.get("MAIL_USERNAME"),
            current_app.config.get("MAIL_PASSWORD"),
        )
        server.send_message(msg)
        server.quit()
    except Exception as e:
        logger.error(f"Email send error: {e}")


def _send_telegram(chat_id: str, text: str):
    try:
        import requests
        from flask import current_app
        token = current_app.config.get("TELEGRAM_BOT_TOKEN")
        if not token:
            return
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=5,
        )
    except Exception as e:
        logger.error(f"Telegram send error: {e}")


def register_notification_jobs(scheduler, app):
    scheduler.add_job(send_pending_notifications, "interval", seconds=30,
                      args=[app], id="send_notifications", replace_existing=True)
    logger.info("Notification jobs registered")
