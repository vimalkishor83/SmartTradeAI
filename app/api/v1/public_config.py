"""Public (no-auth) site configuration — safe-to-expose settings a logged-
out page needs, starting with social media links. Distinct from
/api/v1/admin/platform-config (which returns the full config and requires
an admin session): this endpoint hand-picks only the fields that are
genuinely safe for an anonymous visitor to read, so a future admin-only
field added to PlatformConfig doesn't leak here by accident.
"""
from urllib.parse import urlparse

from flask import Blueprint, jsonify
from app.extensions import cache, limiter

public_config_bp = Blueprint("public_config", __name__)


_SOCIAL_HOSTS = {
    "facebook": ("facebook.com", "www.facebook.com"),
    "instagram": ("instagram.com", "www.instagram.com"),
    "x": ("x.com", "www.x.com", "twitter.com", "www.twitter.com"),
    "linkedin": ("linkedin.com", "www.linkedin.com"),
    "youtube": ("youtube.com", "www.youtube.com"),
    "telegram": ("t.me", "telegram.me", "telegram.org"),
    "discord": ("discord.gg", "discord.com", "www.discord.com"),
}


def _valid_social_url(platform, value):
    """Return an official, non-root profile URL or an empty string.

    Admin configuration is user-entered, so the anonymous endpoint must not
    publish placeholders, malformed URLs, or a different platform's link.
    """
    if not isinstance(value, str):
        return ""
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in _SOCIAL_HOSTS.get(platform, ()):
        return ""
    if not parsed.path.strip("/"):
        return ""
    return value


@public_config_bp.route("/site-config", methods=["GET"])
@limiter.limit("60 per minute", override_defaults=True)
@cache.cached(timeout=300, key_prefix="public_site_config")
def site_config():
    from app.services.platform_config import get_platform_config
    cfg = get_platform_config()
    social = {
        "facebook": cfg.get("social_facebook") or "",
        "instagram": cfg.get("social_instagram") or "",
        "x": cfg.get("social_x") or "",
        "linkedin": cfg.get("social_linkedin") or "",
        "youtube": cfg.get("social_youtube") or "",
        "telegram": cfg.get("social_telegram") or "",
        "discord": cfg.get("social_discord") or "",
    }
    # Only publish validated profile URLs. A bare platform homepage or a
    # cross-platform placeholder (for example LinkedIn -> Telegram) is not a
    # useful public link and should be hidden until corrected by an admin.
    social = {k: _valid_social_url(k, v) for k, v in social.items()}
    social = {k: v for k, v in social.items() if v}
    return jsonify({"social_links": social}), 200
