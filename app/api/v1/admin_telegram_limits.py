import re

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.auth.decorators import admin_required, super_admin_required
from app.extensions import db
from app.models.asset import Asset
from app.models.telegram_individual_signal_limit import TelegramIndividualSignalLimit


admin_telegram_limits_bp = Blueprint("admin_telegram_limits", __name__)


def _available_timeframes():
    from app.services.platform_config import get_display_timeframes

    return get_display_timeframes()


@admin_telegram_limits_bp.route("/telegram-signal-limits", methods=["GET"])
@admin_required
def get_telegram_signal_limits():
    assets = Asset.query.filter_by(is_active=True).order_by(Asset.market, Asset.symbol).all()
    return jsonify({
        "settings": TelegramIndividualSignalLimit.get_singleton().to_dict(),
        "timeframes": _available_timeframes(),
        "assets": [
            {
                "id": asset.id,
                "symbol": asset.symbol,
                "name": asset.name,
                "market": asset.market,
            }
            for asset in assets
        ],
    }), 200


@admin_telegram_limits_bp.route("/telegram-signal-limits", methods=["PUT"])
@super_admin_required
def update_telegram_signal_limits():
    data = request.get_json(silent=True) or {}
    assets = Asset.query.filter_by(is_active=True).all()
    active_asset_ids = {asset.id for asset in assets}
    available_timeframes = set(_available_timeframes())

    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        return jsonify({"error": "enabled must be true or false"}), 400

    asset_ids = data.get("asset_ids")
    if asset_ids is not None:
        if not isinstance(asset_ids, list):
            return jsonify({"error": "asset_ids must be null or a list"}), 400
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in asset_ids):
            return jsonify({"error": "asset_ids must contain integer asset ids"}), 400
        if len(set(asset_ids)) != len(asset_ids):
            return jsonify({"error": "asset_ids must not contain duplicates"}), 400
        unknown = sorted(set(asset_ids) - active_asset_ids)
        if unknown:
            return jsonify({"error": f"asset_ids contains inactive or unknown assets: {unknown}"}), 400

    timeframes = data.get("timeframes")
    if timeframes is not None:
        if not isinstance(timeframes, list):
            return jsonify({"error": "timeframes must be null or a list"}), 400
        if not all(isinstance(tf, str) and re.match(r"^\d+[mhdw]$", tf) for tf in timeframes):
            return jsonify({"error": "timeframes contains an invalid timeframe token"}), 400
        if len(set(timeframes)) != len(timeframes):
            return jsonify({"error": "timeframes must not contain duplicates"}), 400
        unknown = sorted(set(timeframes) - available_timeframes)
        if unknown:
            return jsonify({"error": f"timeframes are not currently available: {unknown}"}), 400

    row = TelegramIndividualSignalLimit.get_singleton()
    row.enabled = enabled
    row.asset_ids = asset_ids
    row.timeframes = timeframes
    row.updated_by = int(get_jwt_identity())
    db.session.commit()

    from app.services.notifications.telegram_individual_signal_limits import (
        invalidate_telegram_individual_signal_limits,
    )

    invalidate_telegram_individual_signal_limits()
    return jsonify({"settings": row.to_dict()}), 200
