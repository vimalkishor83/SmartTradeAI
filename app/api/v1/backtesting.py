from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from app.extensions import db
from app.models.backtest import Backtest
from app.models.asset import Asset
from app.auth.decorators import login_required, premium_required
from app.services.backtesting.engine import backtest_engine
from app.services.data.fetcher import market_fetcher
from datetime import datetime

backtesting_bp = Blueprint("backtesting", __name__)


@backtesting_bp.route("/", methods=["GET"])
@login_required
def list_backtests():
    user_id = get_jwt_identity()
    tests = Backtest.query.filter_by(user_id=user_id) \
        .order_by(Backtest.created_at.desc()).limit(50).all()
    return jsonify({"backtests": [t.to_dict() for t in tests]}), 200


@backtesting_bp.route("/run", methods=["POST"])
@premium_required
def run_backtest():
    user_id = get_jwt_identity()
    data = request.get_json()

    symbol = data.get("symbol")
    timeframe = data.get("timeframe", "1h")
    initial_capital = float(data.get("initial_capital", 100000))

    asset = Asset.query.filter_by(symbol=symbol, is_active=True).first()
    if not asset:
        return jsonify({"error": "Asset not found"}), 404

    bt = Backtest(
        user_id=user_id,
        asset_id=asset.id,
        strategy_name=data.get("strategy", "Default Multi-Indicator"),
        timeframe=timeframe,
        initial_capital=initial_capital,
        status="running",
    )
    db.session.add(bt)
    db.session.commit()

    df = market_fetcher.fetch(asset, timeframe, 1000)
    if df is None:
        bt.status = "failed"
        db.session.commit()
        return jsonify({"error": "Failed to fetch data"}), 503

    result = backtest_engine.run(df, asset, timeframe, initial_capital)

    if "error" in result:
        bt.status = "failed"
        db.session.commit()
        return jsonify(result), 422

    bt.status = "completed"
    bt.completed_at = datetime.utcnow()
    for k, v in result.items():
        if hasattr(bt, k):
            setattr(bt, k, v)

    db.session.commit()
    return jsonify(bt.to_dict()), 200


@backtesting_bp.route("/<int:bt_id>", methods=["GET"])
@login_required
def get_backtest(bt_id):
    user_id = get_jwt_identity()
    bt = Backtest.query.filter_by(id=bt_id, user_id=user_id).first_or_404()
    result = bt.to_dict()
    result["equity_curve"] = bt.equity_curve
    result["trades_data"] = bt.trades_data
    return jsonify(result), 200
