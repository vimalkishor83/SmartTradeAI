from flask import Blueprint, request, jsonify
from app.auth.decorators import login_required
from app.services.risk.calculator import (
    calculate_position,
    calculate_position_volatility,
    calculate_risk_reward,
)

risk_bp = Blueprint("risk", __name__)


@risk_bp.route("/position-size", methods=["POST"])
@login_required
def position_size():
    """
    Calculate position size.
    If `atr` is supplied, uses volatility-adjusted sizing (recommended).
    Optional `atr_history` list of recent ATR values enables percentile-based regime detection.
    """
    data = request.get_json()
    try:
        capital   = float(data["capital"])
        risk_pct  = float(data["risk_pct"])
        entry     = float(data["entry"])
        stop_loss = float(data["stop_loss"])
        lot_size  = float(data.get("lot_size", 1.0))
        atr       = data.get("atr")
        atr_hist  = data.get("atr_history")   # optional list of recent ATR values

        if atr:
            result = calculate_position_volatility(
                capital=capital, risk_pct=risk_pct, entry=entry, stop_loss=stop_loss,
                atr=float(atr), atr_lookback_values=atr_hist, lot_size=lot_size,
            )
        else:
            result = calculate_position(
                capital=capital, risk_pct=risk_pct, entry=entry,
                stop_loss=stop_loss, lot_size=lot_size,
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
