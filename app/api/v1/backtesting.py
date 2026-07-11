from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from app.extensions import db
from app.models.backtest import Backtest
from app.models.asset import Asset
from app.auth.decorators import login_required, premium_required, subscription_feature_required
from app.services.backtesting.engine import backtest_engine
from app.services.backtesting.walk_forward import run_walk_forward
from app.services.data.fetcher import market_fetcher
from datetime import datetime

# Shared across /run and /walk-forward — keeps strategy-name normalization
# in one place instead of duplicating the dict.
_STRATEGY_MAP = {
    "rsi":          "rsi",
    "rsi_strategy": "rsi",
    "macd":         "macd",
    "macd_strategy":"macd",
    "ema":          "ema_crossover",
    "ema_crossover":"ema_crossover",
    "ema_cross":    "ema_crossover",
    "multi_factor": "multi_factor",
    "multi":        "multi_factor",
}


def _resolve_strategy(raw: str | None) -> str:
    key = (raw or "multi_factor").lower().replace(" ", "_")
    return _STRATEGY_MAP.get(key, "multi_factor")

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
@subscription_feature_required("backtesting_enabled")
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

    engine_strategy = _resolve_strategy(data.get("strategy"))

    # Allow caller to override defaults; clamp to sane ranges
    commission = max(0.0, min(0.01, float(data.get("commission", 0.001))))
    slippage   = max(0.0, min(0.01, float(data.get("slippage",   0.0005))))

    result = backtest_engine.run(
        df, asset, timeframe, initial_capital,
        strategy=engine_strategy,
        commission=commission,
        slippage=slippage,
    )

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


@backtesting_bp.route("/walk-forward", methods=["POST"])
@premium_required
@subscription_feature_required("backtesting_enabled")
def walk_forward():
    """
    Splits history into N sequential windows and runs the same strategy
    on each independently, so a user can see whether a strategy's edge
    held up consistently across different historical stretches instead of
    trusting one full-history backtest number that may just reflect one
    lucky (or unlucky) regime. Not persisted as a Backtest row — this is
    a diagnostic view, not a single canonical result the way /run is.
    """
    data = request.get_json() or {}

    symbol = data.get("symbol")
    timeframe = data.get("timeframe", "1h")
    initial_capital = float(data.get("initial_capital", 100000))
    n_windows = max(2, min(10, int(data.get("n_windows", 5))))

    asset = Asset.query.filter_by(symbol=symbol, is_active=True).first()
    if not asset:
        return jsonify({"error": "Asset not found"}), 404

    engine_strategy = _resolve_strategy(data.get("strategy"))

    # multi_factor calls signal_engine.generate_signal() once per bar
    # (a full 7-stage pipeline including calculate_all_indicators +
    # pattern detection) -- measured at ~70ms/bar vs ~0.5ms/bar for the
    # pre-computed-series rsi/macd/ema_crossover paths, so a multi_factor
    # walk-forward run over the same candle volume takes roughly 100x
    # longer. Capping its window count/candle volume keeps a single HTTP
    # request bounded to a reasonable wall-clock time instead of the
    # Flask worker blocking for minutes.
    if engine_strategy == "multi_factor":
        n_windows = min(n_windows, 3)
        candle_target = min(1500, max(900, n_windows * 300))
    else:
        # Walk-forward needs meaningfully more history per window than a
        # single /run backtest to keep each window above _MIN_WINDOW_BARS
        # — fetch a larger set than /run's fixed 1000.
        candle_target = max(2000, n_windows * 300)

    df = market_fetcher.fetch(asset, timeframe, candle_target)
    if df is None:
        return jsonify({"error": "Failed to fetch data"}), 503
    commission = max(0.0, min(0.01, float(data.get("commission", 0.001))))
    slippage   = max(0.0, min(0.01, float(data.get("slippage",   0.0005))))

    result = run_walk_forward(
        df, asset, timeframe, initial_capital,
        strategy=engine_strategy, commission=commission, slippage=slippage,
        n_windows=n_windows,
    )
    if "error" in result:
        return jsonify(result), 422
    return jsonify(result), 200


@backtesting_bp.route("/<int:bt_id>", methods=["GET"])
@login_required
def get_backtest(bt_id):
    user_id = get_jwt_identity()
    bt = Backtest.query.filter_by(id=bt_id, user_id=user_id).first_or_404()
    result = bt.to_dict()
    result["equity_curve"] = bt.equity_curve
    result["trades_data"] = bt.trades_data
    return jsonify(result), 200
