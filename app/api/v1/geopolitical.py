"""
Geopolitical risk dashboard — public/no-auth, matches the reference site's
free "Explorer" dashboard tier. Read-only, no personal data.
"""
from datetime import datetime, timezone
from flask import Blueprint, jsonify
from app.extensions import cache
from app.services.geopolitical.fetcher import fetch_geopolitical_risk

geopolitical_bp = Blueprint("geopolitical", __name__)

_CACHE_KEY = "geopolitical_risk"
_CACHE_TTL = 900  # 15 min — GDELT is slow/throttled; this is not a live-tick indicator


@geopolitical_bp.route("/", methods=["GET"])
def get_geopolitical_risk():
    cached = cache.get(_CACHE_KEY)
    if cached:
        return jsonify(cached), 200

    data = fetch_geopolitical_risk()
    payload = {"data": data, "cached_at": datetime.now(timezone.utc).isoformat()}
    cache.set(_CACHE_KEY, payload, timeout=_CACHE_TTL)
    return jsonify(payload), 200
