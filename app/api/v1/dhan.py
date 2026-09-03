"""Dhan (DhanHQ) endpoints — Indices and Options only, for now.

Entirely new and isolated: nothing else in the app calls into this
blueprint or depends on it, so it can't interrupt anything currently
running. Backed by app/services/data/dhan_fetcher.py, which itself no-ops
gracefully until an admin saves a "dhan" APIConfig row (Admin > API
Configurations > Add Configuration > Market: Indices > Provider: Dhan).
"""
from flask import Blueprint, request, jsonify
from app.auth.decorators import login_required
from app.services.data import dhan_fetcher

dhan_bp = Blueprint("dhan", __name__)


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
    if not dhan_fetcher.is_configured():
        return jsonify({"configured": False, "quotes": {}}), 200
    names_param = request.args.get("names")
    names = [n.strip() for n in names_param.split(",")] if names_param else None
    quotes = dhan_fetcher.fetch_index_quotes(names)
    return jsonify({"configured": True, "quotes": quotes}), 200


@dhan_bp.route("/options/expiries", methods=["GET"])
@login_required
def option_expiries():
    underlying = request.args.get("underlying", "")
    if not dhan_fetcher.is_configured():
        return jsonify({"configured": False, "expiries": []}), 200
    if underlying not in dhan_fetcher.INDEX_SECURITY_IDS:
        return jsonify({"error": f"Unknown underlying '{underlying}'",
                         "available": list(dhan_fetcher.INDEX_SECURITY_IDS.keys())}), 422
    return jsonify({"configured": True, "expiries": dhan_fetcher.fetch_option_expiries(underlying)}), 200


@dhan_bp.route("/options/chain", methods=["GET"])
@login_required
def option_chain():
    underlying = request.args.get("underlying", "")
    expiry = request.args.get("expiry", "")
    if not dhan_fetcher.is_configured():
        return jsonify({"configured": False, "chain": {}}), 200
    if underlying not in dhan_fetcher.INDEX_SECURITY_IDS:
        return jsonify({"error": f"Unknown underlying '{underlying}'",
                         "available": list(dhan_fetcher.INDEX_SECURITY_IDS.keys())}), 422
    if not expiry:
        return jsonify({"error": "expiry is required (see /options/expiries)"}), 422
    return jsonify({"configured": True, "chain": dhan_fetcher.fetch_option_chain(underlying, expiry)}), 200
