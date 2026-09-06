"""User-owned Delta Exchange India algo execution policy API.

This module only stores and previews guardrails. It intentionally does not
place live orders; execution will consume this policy in a later slice.
"""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.auth.decorators import login_required
from app.extensions import db
from app.models.algo_trading import AlgoExecutionPolicy, DEFAULT_ORDER_RULES
from app.services.trading.algo_policy import validate_policy_payload, preview_order


algo_trading_bp = Blueprint("algo_trading", __name__)


def _policy_for_user(user_id):
    policy = AlgoExecutionPolicy.query.filter_by(user_id=int(user_id)).first()
    if policy:
        return policy
    policy = AlgoExecutionPolicy(user_id=int(user_id), order_rules=dict(DEFAULT_ORDER_RULES))
    db.session.add(policy)
    db.session.commit()
    return policy


@algo_trading_bp.route("/policy", methods=["GET"])
@login_required
def get_policy():
    return jsonify({"policy": _policy_for_user(get_jwt_identity()).to_dict()}), 200


@algo_trading_bp.route("/policy", methods=["PUT"])
@login_required
def update_policy():
    data = request.get_json(silent=True)
    try:
        values = validate_policy_payload(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Live enablement is deliberately a separate execution rollout concern.
    # This policy endpoint can configure live mode, but never enables it.
    values["enabled"] = False
    policy = _policy_for_user(get_jwt_identity())
    for field, value in values.items():
        setattr(policy, field, value)
    policy.execution_provider = "delta_exchange_india"
    db.session.commit()
    return jsonify({"policy": policy.to_dict(), "message": "Policy saved. Algo execution remains disabled until explicitly activated."}), 200


@algo_trading_bp.route("/policy/preview", methods=["POST"])
@login_required
def preview_policy_order():
    policy = _policy_for_user(get_jwt_identity())
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400
    try:
        result = preview_order(
            policy,
            price=data.get("price"),
            requested_size=data.get("requested_size"),
            contract_multiplier=data.get("contract_multiplier", 1),
            leverage=data.get("leverage", 1),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"preview": result, "execution_provider": "delta_exchange_india", "mode": policy.mode}), 200
