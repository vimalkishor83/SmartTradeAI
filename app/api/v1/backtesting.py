from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from app.extensions import db
from app.models.backtest import Backtest
from app.models.asset import Asset
from app.auth.decorators import login_required, premium_required, subscription_feature_required
from app.services.backtesting.engine import backtest_engine
from app.services.backtesting.walk_forward import run_walk_forward
from app.services.data.fetcher import market_fetcher
from app.services.backtest.validation import parse_strategy_payload
from app.services.backtesting.reproducibility import BACKTEST_ENGINE_VERSION
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
    try:
        config = parse_strategy_payload(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    symbol = config["symbol"]
    timeframe = config["timeframe"]
    initial_capital = config["initial_capital"]

    asset = Asset.query.filter_by(symbol=symbol, is_active=True).first()
    if not asset:
        return jsonify({"error": "Asset not found"}), 404

    bt = Backtest(
        user_id=user_id,
        asset_id=asset.id,
        strategy_name=config["strategy"],
        timeframe=timeframe,
        initial_capital=initial_capital,
        status="running",
    )
    db.session.add(bt)
    db.session.commit()

    engine_strategy = _resolve_strategy(config["strategy"])

    # multi_factor calls signal_engine.generate_signal() once per bar (a full
    # 7-stage pipeline including calculate_all_indicators + pattern
    # detection), measured at ~70ms/bar vs ~0.5ms/bar for the
    # pre-computed-series rsi/macd/ema_crossover paths. At the fixed 1000
    # candles every strategy used to fetch here, that's ~940 sequential
    # full-pipeline calls (~65s) blocking one Flask worker thread for the
    # whole request — the exact cost /walk-forward already caps for the same
    # reason. Apply the same cap here rather than only on the windowed
    # endpoint.
    candle_count = 600 if engine_strategy == "multi_factor" else 1000

    df = market_fetcher.fetch(asset, timeframe, candle_count)
    if df is None:
        bt.status = "failed"
        db.session.commit()
        return jsonify({"error": "Failed to fetch data"}), 503

    commission = config["commission"]
    slippage = config["slippage"]
    spread = config["spread"]

    result = backtest_engine.run(
        df, asset, timeframe, initial_capital,
        strategy=engine_strategy,
        commission=commission,
        slippage=slippage,
        spread=spread,
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

    provenance = result.get("reproducibility") or {}
    bt.engine_version = provenance.get("engine_version", BACKTEST_ENGINE_VERSION)
    bt.model_version = provenance.get("model_version")
    bt.config_fingerprint = provenance.get("config_fingerprint")
    bt.data_fingerprint = provenance.get("data_fingerprint")
    bt.data_candles = provenance.get("data_candles")
    if provenance.get("data_start"):
        bt.start_date = datetime.fromisoformat(provenance["data_start"].replace("Z", "+00:00")).replace(tzinfo=None)
    if provenance.get("data_end"):
        bt.end_date = datetime.fromisoformat(provenance["data_end"].replace("Z", "+00:00")).replace(tzinfo=None)

    db.session.commit()
    # equity_curve/trades_data are stored on the row (assigned via the
    # setattr loop above) but deliberately excluded from to_dict() — see
    # Backtest.to_dict()'s comment — since list_backtests() uses the same
    # method for up to 50 history rows. This is the single-result-just-ran
    # response the Backtesting page's chart and trade table read directly,
    # so it needs the detail fields the same way get_backtest() already
    # bolts them on for a saved backtest's detail view. Without this, both
    # were silently always empty for every non-live/strategy-config
    # backtest despite the data existing in the database the whole time.
    response = bt.to_dict()
    response["equity_curve"] = bt.equity_curve
    response["trades_data"] = bt.trades_data
    return jsonify(response), 200


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
    try:
        config = parse_strategy_payload(request.get_json(silent=True), include_windows=True)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    symbol = config["symbol"]
    timeframe = config["timeframe"]
    initial_capital = config["initial_capital"]
    n_windows = config["n_windows"]

    asset = Asset.query.filter_by(symbol=symbol, is_active=True).first()
    if not asset:
        return jsonify({"error": "Asset not found"}), 404

    engine_strategy = _resolve_strategy(config["strategy"])

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
    commission = config["commission"]
    slippage = config["slippage"]
    spread = config["spread"]

    result = run_walk_forward(
        df, asset, timeframe, initial_capital,
        strategy=engine_strategy, commission=commission, slippage=slippage,
        spread=spread,
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
