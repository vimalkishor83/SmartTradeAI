"""Web Push notification sender using VAPID + pywebpush."""
import json
import logging

logger = logging.getLogger(__name__)


def send_push_notification(subscription_json: str, title: str, body: str,
                           icon: str = "/static/icons/icon-192.png",
                           url: str = "/dashboard") -> bool:
    """
    Send a Web Push notification to a single subscription.
    subscription_json — the JSON string from browser PushSubscription.toJSON()
    Returns True on success, False on failure.
    """
    try:
        from flask import current_app
        from pywebpush import webpush, WebPushException

        vapid_private = current_app.config.get("VAPID_PRIVATE_KEY")
        vapid_claims  = {
            "sub": current_app.config.get("VAPID_CLAIMS_EMAIL", "mailto:admin@smarttradeai.com")
        }

        if not vapid_private:
            logger.debug("VAPID_PRIVATE_KEY not configured — skipping push")
            return False

        subscription_info = json.loads(subscription_json) if isinstance(subscription_json, str) else subscription_json

        payload = json.dumps({
            "title": title,
            "body":  body,
            "icon":  icon,
            "url":   url,
        })

        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=vapid_private,
            vapid_claims=vapid_claims,
        )
        return True

    except Exception as e:
        logger.warning(f"Web Push send failed: {e}")
        # If subscription is expired/gone (410), caller should clean it up
        return False


def send_push_to_user(user, title: str, body: str, url: str = "/dashboard") -> bool:
    """Send push to a user if they have a valid subscription and push enabled."""
    if not user.push_enabled or not user.push_subscription:
        return False
    return send_push_notification(user.push_subscription, title, body, url=url)
