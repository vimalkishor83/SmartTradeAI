"""Dhan (DhanHQ) endpoints — Indices and Options only, for now.

Entirely new and isolated: nothing else in the app calls into this
blueprint or depends on it, so it can't interrupt anything currently
running. Backed by app/services/data/dhan_fetcher.py, which itself no-ops
gracefully until an admin saves a "dhan" APIConfig row (Admin > API
Configurations > Add Configuration > Market: Indices > Provider: Dhan).
"""
from datetime import date
import re

from flask import Blueprint, request, jsonify
from app.auth.decorators import login_required
from app.services.data import dhan_fetcher

dhan_bp = Blueprint("dhan", __name__)
_EXPIRY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_INDEX_NAMES = 3


def _canonical_underlying(value):
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    return next(
        (name for name in dhan_fetcher.INDEX_SECURITY_IDS if name.casefold() == normalized),
        None,
    )


def _parse_index_names(value):
    if value is None:
        return None, None
    names = []
    for raw_name in value.split(","):
        if not raw_name.strip():
            continue
        name = _canonical_underlying(raw_name)
        if not name:
            return None, f"Unknown underlying '{raw_name.strip()}'"
        if name not in names:
            names.append(name)
    if not names:
        return None, "names must include at least one supported underlying"
    if len(names) > _MAX_INDEX_NAMES:
        return None, f"At most {_MAX_INDEX_NAMES} underlyings can be requested"
    return names, None


def _valid_expiry(value):
    if not isinstance(value, str):
        return False
    value = value.strip()
    if not _EXPIRY_RE.fullmatch(value):
        return False
    try:
        return date.fromisoformat(value) >= date.today()
    except ValueError:
        return False


@dhan_bp.route("/status", methods=["GET"])
@login_required
def status():
    return jsonify({
        "configured": dhan_fetcher.is_configured(),
        "available_underlyings": list(dhan_fetcher.INDEX_SECURITY_IDS.keys()),
    }), 200


@dhan_bp.route("/indices", methods=["GET"])
@login_required
def indices():
    names_param = request.args.get("names")
    names, error = _parse_index_names(names_param)
    if error:
        return jsonify({"error": error, "available": list(dhan_fetcher.INDEX_SECURITY_IDS.keys())}), 422
    if not dhan_fetcher.is_configured():
        return jsonify({"configured": False, "quotes": {}}), 200
    quotes = dhan_fetcher.fetch_index_quotes(names)
    return jsonify({"configured": True, "quotes": quotes}), 200


@dhan_bp.route("/options/expiries", methods=["GET"])
@login_required
def option_expiries():
    underlying_raw = request.args.get("underlying", "")
    underlying = _canonical_underlying(underlying_raw)
    if not underlying:
        return jsonify({"error": f"Unknown underlying '{underlying_raw}'",
                         "available": list(dhan_fetcher.INDEX_SECURITY_IDS.keys())}), 422
    if not dhan_fetcher.is_configured():
        return jsonify({"configured": False, "expiries": []}), 200
    return jsonify({"configured": True, "expiries": dhan_fetcher.fetch_option_expiries(underlying)}), 200


@dhan_bp.route("/options/chain", methods=["GET"])
@login_required
def option_chain():
    underlying = request.args.get("underlying", "")
    expiry = request.args.get("expiry", "")
    canonical_underlying = _canonical_underlying(underlying)
    if not canonical_underlying:
        return jsonify({"error": f"Unknown underlying '{underlying}'",
                         "available": list(dhan_fetcher.INDEX_SECURITY_IDS.keys())}), 422
    if not _valid_expiry(expiry):
        return jsonify({"error": "expiry must be a valid, non-expired YYYY-MM-DD date"}), 422
    if not dhan_fetcher.is_configured():
        return jsonify({"configured": False, "chain": {}}), 200
    return jsonify({"configured": True, "chain": dhan_fetcher.fetch_option_chain(canonical_underlying, expiry.strip())}), 200
