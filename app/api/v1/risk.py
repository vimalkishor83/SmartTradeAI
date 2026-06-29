from flask import Blueprint, request, jsonify
from app.auth.decorators import login_required
from app.services.risk.calculator import calculate_position, calculate_risk_reward

risk_bp = Blueprint("risk", __name__)


@risk_bp.route("/position-size", methods=["POST"])
@login_required
def position_size():
    data = request.get_json()
    try:
        result = calculate_position(
            capital=float(data["capital"]),
            risk_pct=float(data["risk_pct"]),
            entry=float(data["entry"]),
            stop_loss=float(data["stop_loss"]),
            lot_size=float(data.get("lot_size", 1.0)),
        )
        return jsonify(result), 200
    except (KeyError, ValueError) as e:
        return jsonify({"error": str(e)}), 400


@risk_bp.route("/risk-reward", methods=["POST"])
@login_required
def risk_reward():
    data = request.get_json()
    try:
        result = calculate_risk_reward(
            entry=float(data["entry"]),
            stop_loss=float(data["stop_loss"]),
            target=float(data["target"]),
        )
        return jsonify(result), 200
    except (KeyError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
