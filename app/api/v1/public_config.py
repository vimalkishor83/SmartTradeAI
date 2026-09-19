"""Public (no-auth) site configuration — safe-to-expose settings a logged-
out page needs, starting with social media links. Distinct from
/api/v1/admin/platform-config (which returns the full config and requires
an admin session): this endpoint hand-picks only the fields that are
genuinely safe for an anonymous visitor to read, so a future admin-only
field added to PlatformConfig doesn't leak here by accident.
"""
import logging

from flask import Blueprint, jsonify

public_config_bp = Blueprint("public_config", __name__)
logger = logging.getLogger(__name__)


@public_config_bp.route("/site-config", methods=["GET"])
def site_config():
    # Called on every anonymous page load, unauthenticated, high-traffic —
    # a transient DB/cache hiccup here should degrade to "no social icons
    # shown" like every other public data service in this app, not a 500.
    try:
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
        # Only ever include platforms an admin has actually configured — a
        # public page should never see an empty string and have to remember
        # to check truthiness itself.
        social = {k: v for k, v in social.items() if v}
    except Exception as exc:
        logger.warning("site_config failed, returning empty social links: %s", type(exc).__name__)
        social = {}
    return jsonify({"social_links": social}), 200
