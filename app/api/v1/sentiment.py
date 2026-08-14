"""
Market sentiment dashboard — public/no-auth, matches the reference site's
free "Explorer" dashboard tier. Read-only, no personal data.
"""
from datetime import datetime, timezone
from flask import Blueprint, jsonify
from app.extensions import cache
from app.services.sentiment.fear_greed import fetch_fear_greed

sentiment_bp = Blueprint("sentiment", __name__)

_CACHE_KEY = "fear_greed_index"
_CACHE_TTL = 900  # 15 min — index updates roughly daily upstream


@sentiment_bp.route("/fear-greed", methods=["GET"])
def get_fear_greed():
    cached = cache.get(_CACHE_KEY)
    if cached:
        return jsonify(cached), 200

    data = fetch_fear_greed()
    payload = {"data": data, "cached_at": datetime.now(timezone.utc).isoformat()}
    cache.set(_CACHE_KEY, payload, timeout=_CACHE_TTL)
    return jsonify(payload), 200
