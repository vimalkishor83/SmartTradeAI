"""
Forex strength dashboard — public/no-auth, matches the reference site's
free "Explorer" dashboard tier. Read-only, no personal data.
"""
from datetime import datetime, timezone
from flask import Blueprint, jsonify
from app.extensions import cache
from app.services.forex.fetcher import fetch_forex_strength

forex_bp = Blueprint("forex", __name__)

_CACHE_KEY = "forex_strength"
_CACHE_TTL = 900  # 15 min — ECB rates update once/day, no need to hammer upstream


@forex_bp.route("/", methods=["GET"])
def get_forex_strength():
    cached = cache.get(_CACHE_KEY)
    if cached:
        return jsonify(cached), 200

    data = fetch_forex_strength()
    payload = {"data": data, "cached_at": datetime.now(timezone.utc).isoformat()}
    cache.set(_CACHE_KEY, payload, timeout=_CACHE_TTL)
    return jsonify(payload), 200
