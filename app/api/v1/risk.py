import math

from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from app.auth.decorators import login_required
from app.services.risk.calculator import (
    calculate_position,
    calculate_position_volatility,
    calculate_risk_reward,
)
from app.services.risk.portfolio_risk import (
    calculate_correlation_matrix,
    calculate_concentration,
)

risk_bp = Blueprint("risk", __name__)

_MAX_RISK_NUMBER = 1_000_000_000_000.0
_MAX_LOT_SIZE = 1_000_000.0
_MAX_ATR_HISTORY = 500


def _finite_number(data: dict, field: str, *, minimum: float, maximum: float,
                   default: float | None = None) -> float:
    """Parse bounded numeric input before it reaches sizing math."""
    raw = data[field] if default is None else data.get(field, default)
    if isinstance(raw, bool):
        raise ValueError(f"{field} must be a number")
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{field} must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{field} must be finite")
    if value < minimum or value > maximum:
        raise ValueError(f"{field} must be between {minimum:g} and {maximum:g}")
    return value


@risk_bp.route("/position-size", methods=["POST"])
@login_required
def position_size():
    """
    Calculate position size.
    If `atr` is supplied, uses volatility-adjusted sizing (recommended).
    Optional `atr_history` list of recent ATR values enables percentile-based regime detection.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400
    try:
        capital   = _finite_number(data, "capital", minimum=0.000001, maximum=_MAX_RISK_NUMBER)
        risk_pct  = _finite_number(data, "risk_pct", minimum=0.000001, maximum=100.0)
        entry     = _finite_number(data, "entry", minimum=0.000001, maximum=_MAX_RISK_NUMBER)
        stop_loss = _finite_number(data, "stop_loss", minimum=0.000001, maximum=_MAX_RISK_NUMBER)
        lot_size  = _finite_number(data, "lot_size", minimum=0.000001, maximum=_MAX_LOT_SIZE, default=1.0)
        atr       = data.get("atr")
        atr_hist  = data.get("atr_history")   # optional list of recent ATR values

        if atr is not None and atr != "":
            atr = _finite_number(data, "atr", minimum=0.0, maximum=_MAX_RISK_NUMBER)
            if atr_hist is not None:
                if not isinstance(atr_hist, list) or len(atr_hist) > _MAX_ATR_HISTORY:
                    raise ValueError(f"atr_history must be a list of at most {_MAX_ATR_HISTORY} values")
                atr_hist = [
                    _finite_number({"value": value}, "value", minimum=0.0, maximum=_MAX_RISK_NUMBER)
                    for value in atr_hist
                ]
            result = calculate_position_volatility(
                capital=capital, risk_pct=risk_pct, entry=entry, stop_loss=stop_loss,
                atr=atr, atr_lookback_values=atr_hist, lot_size=lot_size,
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
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400
    try:
        result = calculate_risk_reward(
            entry=_finite_number(data, "entry", minimum=0.000001, maximum=_MAX_RISK_NUMBER),
            stop_loss=_finite_number(data, "stop_loss", minimum=0.000001, maximum=_MAX_RISK_NUMBER),
            target=_finite_number(data, "target", minimum=0.000001, maximum=_MAX_RISK_NUMBER),
        )
        return jsonify(result), 200
    except (KeyError, ValueError) as e:
        return jsonify({"error": str(e)}), 400


@risk_bp.route("/portfolio", methods=["GET"])
@login_required
def portfolio_risk():
    """
    Portfolio-level risk view: pairwise return correlation across all open
    holdings (60-day daily closes) plus concentration warnings by symbol
    and by market/asset-class. Per-trade sizing (position-size,
    risk-reward above) can't see this -- a portfolio of 5 individually
    "safe" trades can still be one correlated macro move away from a much
    larger combined drawdown than any single trade's own risk_pct implies.
    """
    from app.extensions import db
    from app.models.portfolio import Portfolio, PortfolioItem
    from app.services.data.fetcher import market_fetcher

    user_id = get_jwt_identity()
    portfolio = Portfolio.query.filter_by(user_id=user_id).first()
    if not portfolio:
        return jsonify({"holdings": 0, "correlation": {"symbols": [], "matrix": [], "high_correlation_pairs": []},
                        "concentration": {"total_value": 0, "by_symbol": [], "by_market": [], "warnings": []}}), 200

    # joinedload: same N+1 that GET /portfolio/ already had to fix (asset is
    # lazy-loaded by default) — this route just hadn't had any real traffic
    # yet to expose it, since nothing in the UI called it until now.
    items = [i for i in portfolio.items.options(db.joinedload(PortfolioItem.asset)).all() if i.asset]
    if not items:
        return jsonify({"holdings": 0, "correlation": {"symbols": [], "matrix": [], "high_correlation_pairs": []},
                        "concentration": {"total_value": 0, "by_symbol": [], "by_market": [], "warnings": []}}), 200

    assets = [i.asset for i in items]
    # 60 daily bars is enough for a meaningful short-term correlation read
    # without dragging in a stale multi-year relationship that may no
    # longer hold (e.g. two assets that decoupled after a regime change).
    data = market_fetcher.fetch_many(assets, ["1d"], limit=60)

    price_history = {}
    for item in items:
        dfs = data.get(item.asset.symbol, {})
        df = dfs.get("1d")
        if df is not None and not df.empty:
            price_history[item.asset.symbol] = df["close"]

    correlation = calculate_correlation_matrix(price_history)

    holdings_for_conc = [
        {"symbol": i.asset.symbol, "market": i.asset.market, "value": i.current_value}
        for i in items
    ]
    concentration = calculate_concentration(holdings_for_conc)

    return jsonify({
        "holdings": len(items),
        "correlation": correlation,
        "concentration": concentration,
    }), 200
