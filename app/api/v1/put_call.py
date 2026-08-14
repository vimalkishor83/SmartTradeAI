"""
Put/call ratio dashboard — public/no-auth, matches the reference site's
free "Explorer" dashboard tier. Read-only, no personal data.
"""
from datetime import datetime, timezone
from flask import Blueprint, jsonify
from app.extensions import cache
from app.services.options.put_call import fetch_put_call_ratio

put_call_bp = Blueprint("put_call", __name__)

_CACHE_KEY = "put_call_ratio"
_CACHE_TTL = 300  # 5 min — Deribit is live, worth refreshing more often than the others


@put_call_bp.route("/", methods=["GET"])
def get_put_call_ratio():
    cached = cache.get(_CACHE_KEY)
    if cached:
        return jsonify(cached), 200

    data = fetch_put_call_ratio()
    payload = {"data": data, "cached_at": datetime.now(timezone.utc).isoformat()}
    cache.set(_CACHE_KEY, payload, timeout=_CACHE_TTL)
    return jsonify(payload), 200
