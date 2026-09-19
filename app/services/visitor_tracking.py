"""New-IP / new-device detection for anonymous homepage visitors.

Persists one row per distinct (ip_address, user_agent) pair ever seen on
the public homepage (VisitorLog) so a repeat visitor never re-triggers a
security alert — only a genuinely new IP, or a new device on an
already-known IP, does. Called from the before_request hook in
app/__init__.py; every failure here is swallowed by the caller, so this
module never needs to worry about breaking a page load.

Rate-limited per IP (not per (ip, user_agent)): the uniqueness key being
(ip, user_agent) means a script that varies its User-Agent on every
request would otherwise trigger an unbounded number of new-row inserts,
geolocation lookups, and Telegram alerts from a single source IP. A
short per-IP cooldown caps this to at most one alert per IP per window,
regardless of how many distinct user agents show up in that window.
"""
import logging
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.extensions import db

logger = logging.getLogger(__name__)

_ALERT_COOLDOWN_SECONDS = 300  # one new-visitor/new-device alert per IP per 5 minutes


def record_visitor_and_alert_if_new(ip_address: str, user_agent: str) -> None:
    if not ip_address:
        return

    from app.models.visitor_log import VisitorLog

    user_agent = (user_agent or "")[:500]
    now = datetime.utcnow()

    existing = VisitorLog.query.filter_by(ip_address=ip_address, user_agent=user_agent).first()
    if existing:
        existing.last_seen_at = now
        existing.visit_count = (existing.visit_count or 0) + 1
        db.session.commit()
        return  # known ip + known device on this ip — nothing to alert

    ip_known_on_other_device = (
        VisitorLog.query.filter_by(ip_address=ip_address).first() is not None
    )

    from app.services.ip_geolocation import lookup_location
    location = lookup_location(ip_address)

    try:
        with db.session.begin_nested():
            db.session.add(VisitorLog(
                ip_address=ip_address,
                user_agent=user_agent,
                location=location,
                first_seen_at=now,
                last_seen_at=now,
                visit_count=1,
            ))
        db.session.commit()
    except IntegrityError:
        # Another concurrent request for this exact (ip, user_agent) pair
        # already inserted it first — that request already alerted (or
        # will), so this one silently backs off rather than double-alerting
        # or crashing the caller's before_request hook.
        db.session.rollback()
        return

    # Cap alert volume per IP regardless of how many distinct user agents
    # show up — the DB row above still records every device for the admin
    # UI, only the Telegram/security-channel alert itself is throttled.
    from app.extensions import cache
    cooldown_key = f"visitor_alert_cooldown:{ip_address}"
    if cache.get(cooldown_key):
        return
    cache.set(cooldown_key, True, timeout=_ALERT_COOLDOWN_SECONDS)

    from app.models.user_session import parse_device_label
    from app.tasks.notification_tasks import send_security_alert
    device = parse_device_label(user_agent)
    when = now.strftime('%Y-%m-%d %H:%M UTC')
    location_line = f"📍 Location: `{location}`\n" if location else ""

    if ip_known_on_other_device:
        text = (
            f"🖥️ *NEW DEVICE ON KNOWN IP*\n\n"
            f"🌐 IP: `{ip_address}`\n"
            f"{location_line}"
            f"💻 Device: {device}\n"
            f"🕐 Time: `{when}`\n\n"
            f"_This IP has visited before, but not from this device._"
        )
    else:
        text = (
            f"🆕 *NEW VISITOR IP*\n\n"
            f"🌐 IP: `{ip_address}`\n"
            f"{location_line}"
            f"💻 Device: {device}\n"
            f"🕐 Time: `{when}`\n\n"
            f"_First time this IP has visited the homepage._"
        )
    try:
        send_security_alert(text)
    except Exception as exc:
        logger.error("New-visitor alert failed: %s", type(exc).__name__)
