"""Walk-forward backtesting for the AI Insights prediction contract.

This module deliberately does not load the live model artifacts. Each
walk-forward checkpoint fits models only on labels that were fully resolved
before that checkpoint, which prevents current-model leakage into historical
results.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.services.ai.predictor import (
    AI_MODEL_VERSION,
    _DIRECTION_THRESHOLD,
    _MIN_TRAIN_ROWS,
    _TB_ATR_MULT,
    _TB_MAX_HOLD,
    _build_features,
    _directional_entry_zone,
    _make_triple_barrier_labels,
    _walk_forward_split,
    ai_predictor,
)
from app.services.backtesting.engine import MAX_HOLD_BARS, backtest_engine
from app.services.backtesting.reproducibility import build_reproducibility_metadata


AI_INSIGHTS_ENGINE_VERSION = "ai-insights-walkforward-v1"
AI_INSIGHTS_STRATEGY = {
    "key": "ai_ensemble",
    "label": "AI Insights Ensemble",
    "description": (
        "Strict walk-forward replay of the AI Insights ensemble, including "
        "triple-barrier labels, calibrated probabilities, ATR risk levels, "
        "and the 60% direction threshold."
    ),
}
AI_INSIGHTS_RETRAIN_EVERY = 20
AI_INSIGHTS_WARMUP = 120


def _fit_calibrated_models(X_train: np.ndarray, y_train: np.ndarray):
    """Fit the same available ensemble members as the live predictor.

    Models are intentionally kept in memory and never written to the live
    model directory. A checkpoint can therefore be reproduced without
    overwriting or reusing the current production prediction artifacts.
    """
    splits = _walk_forward_split(X_train, y_train, n_splits=4)
    if splits:
        fit_idx, calibration_idx = splits[-1]
    else:
        cut = max(1, int(len(X_train) * 0.8))
        fit_idx = np.arange(cut)
        calibration_idx = np.arange(cut, len(X_train))

    X_fit, y_fit = X_train[fit_idx], y_train[fit_idx]
    X_cal, y_cal = X_train[calibration_idx], y_train[calibration_idx]
    models = []

    def add_model(base):
        try:
            base.fit(X_fit, y_fit)
            if len(X_cal) >= 20 and len(np.unique(y_cal)) > 1:
                try:
                    from sklearn.calibration import CalibratedClassifierCV

                    calibrated = CalibratedClassifierCV(base, method="isotonic", cv="prefit")
                    calibrated.fit(X_cal, y_cal)
                    return calibrated
                except Exception:
                    pass
            return base
        except Exception:
            return None

    try:
        from sklearn.ensemble import RandomForestClassifier

        model = add_model(RandomForestClassifier(
            n_estimators=200,
            max_depth=8,
            min_samples_leaf=5,
            random_state=42,
            n_jobs=-1,
        ))
        if model is not None:
            models.append(("random_forest", model))
    except ImportError:
        pass

    try:
        import xgboost as xgb

        model = add_model(xgb.XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric="logloss",
            verbosity=0,
            random_state=42,
        ))
        if model is not None:
            models.append(("xgboost", model))
    except ImportError:
        pass

    try:
        import lightgbm as lgb

        model = add_model(lgb.LGBMClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            verbose=-1,
            random_state=42,
        ))
        if model is not None:
            models.append(("lightgbm", model))
    except ImportError:
        pass

    return models


def _predict_probability(models, features: np.ndarray) -> tuple[float, dict[str, float]]:
    probabilities = {}
    for name, model in models:
        probabilities[name] = float(model.predict_proba(features)[0][1])
    if probabilities:
        return float(np.mean(list(probabilities.values()))), probabilities
    return ai_predictor._heuristic_fallback(features[0]), {"heuristic": ai_predictor._heuristic_fallback(features[0])}


def training_positions_for_checkpoint(
    feature_positions: np.ndarray,
    labels: np.ndarray,
    checkpoint: int,
    *,
    purge_bars: int = _TB_MAX_HOLD,
) -> np.ndarray:
    """Return rows whose labels cannot see beyond a prediction checkpoint."""
    eligible = (
        (feature_positions <= checkpoint - max(0, int(purge_bars)))
        & np.isfinite(labels)
    )
    return np.flatnonzero(eligible)


def _opposite(direction: str) -> str:
    return "SELL" if direction == "BUY" else "BUY"


def _append_exit(
    trades: list[dict],
    position: dict,
    exit_price: float,
    reason: str,
    units: float,
    index_value,
    commission: float,
    slippage: float,
    spread: float,
) -> float:
    fill = backtest_engine._fill_price(exit_price, _opposite(position["type"]), slippage, spread)
    commission_cost = fill * units * commission
    if position["type"] == "BUY":
        gross_pnl = (fill - position["fill"]) * units
    else:
        gross_pnl = (position["fill"] - fill) * units
    ratio = units / position["units"] if position["units"] else 1.0
    entry_commission = position["entry_commission"] * ratio
    net_pnl = gross_pnl - commission_cost - entry_commission
    trades.append({
        "entry": round(position["fill"], 6),
        "exit": round(fill, 6),
        "type": position["type"],
        "bars_held": int(position["current_bar"] - position["bar_index"]),
        "exit_reason": reason,
        "pnl_pct": round(net_pnl / (position["fill"] * units) * 100, 3) if units else 0.0,
        "pnl": round(net_pnl, 2),
        "commission": round(commission_cost + entry_commission, 2),
        "slippage_cost": round(
            position["slippage_cost"] * ratio + abs(fill - exit_price) * units,
            2,
        ),
        "spread_cost": round(
            position["spread_cost"] * ratio + exit_price * spread / 2 * units,
            2,
        ),
        "outcome": "win" if net_pnl > 0 else "loss",
        "date": str(index_value),
        "entry_bar_index": position["bar_index"],
        "leg_units": units,
        "bullish_probability": position.get("bullish_probability"),
        "bearish_probability": (
            1 - position["bullish_probability"]
            if position.get("bullish_probability") is not None else None
        ),
        "entry_range_low": position.get("entry_range_low"),
        "entry_range_high": position.get("entry_range_high"),
    })
    return net_pnl


def run_ai_insights_backtest(
    df: pd.DataFrame,
    asset,
    timeframe: str,
    initial_capital: float = 100_000.0,
    commission: float = 0.001,
    slippage: float = 0.0005,
    spread: float = 0.0,
    *,
    retrain_every: int = AI_INSIGHTS_RETRAIN_EVERY,
) -> dict:
    """Replay the AI Insights model with strict historical checkpoints."""
    if df is None or len(df) < max(160, _MIN_TRAIN_ROWS + _TB_MAX_HOLD + 20):
        return {"error": "Insufficient data for AI walk-forward backtesting"}

    frame = df.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index)
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    frame = frame[["open", "high", "low", "close", "volume"]].astype(float)

    features = _build_features(frame)
    if features.empty:
        return {"error": "Feature engineering produced no usable rows"}

    from app.services.indicators.calculator import calculate_atr

    label_atr = calculate_atr(frame["high"], frame["low"], frame["close"])
    labels = _make_triple_barrier_labels(frame, label_atr)
    feature_positions = frame.index.get_indexer(features.index)
    feature_values = features.to_numpy(dtype=float)
    label_values = labels.loc[features.index].to_numpy(dtype=float)
    range_atr = (frame["high"] - frame["low"]).rolling(20).mean()

    max_hold = MAX_HOLD_BARS.get(timeframe, 10)
    warmup = max(AI_INSIGHTS_WARMUP, int(feature_positions[0]) + 1)
    retrain_every = max(1, int(retrain_every))
    models = None
    last_fit_checkpoint = -retrain_every
    trades: list[dict[str, Any]] = []
    equity = [float(initial_capital)] * min(warmup, len(frame))
    capital = float(initial_capital)
    position = None
    last_close_bar = -1
    prediction_count = 0
    model_checkpoints = 0
    direction_counts = {"bullish": 0, "bearish": 0, "neutral": 0}

    for i in range(warmup, len(frame) - 1):
        current_features = np.flatnonzero(feature_positions == i)
        if len(current_features) == 0:
            equity.append(round(capital, 2))
            continue

        train_idx = training_positions_for_checkpoint(
            feature_positions, label_values, i,
        )
        direction = None
        stop = target1 = target2 = None
        entry_low = entry_high = None
        bull_probability = None
        member_outputs = {}
        if len(train_idx) >= _MIN_TRAIN_ROWS:
            if models is None or i - last_fit_checkpoint >= retrain_every:
                X_train = feature_values[train_idx]
                y_train = label_values[train_idx].astype(int)
                if len(np.unique(y_train)) > 1:
                    models = _fit_calibrated_models(X_train, y_train)
                    last_fit_checkpoint = i
                    model_checkpoints += 1
            bull_probability, member_outputs = _predict_probability(
                models or [], feature_values[current_features[0]][None, :],
            )
            if bull_probability is not None:
                bear_probability = 1.0 - bull_probability
                if bull_probability >= _DIRECTION_THRESHOLD:
                    direction = "BUY"
                    direction_label = "bullish"
                elif bear_probability >= _DIRECTION_THRESHOLD:
                    direction = "SELL"
                    direction_label = "bearish"
                else:
                    direction_label = "neutral"
                direction_counts[direction_label] += 1
                prediction_count += 1

                price = float(frame["close"].iloc[i])
                current_atr = float(range_atr.iloc[i])
                if direction and np.isfinite(current_atr) and current_atr > 0:
                    entry_low, entry_high = _directional_entry_zone(
                        price, current_atr, "bullish" if direction == "BUY" else "bearish",
                    )
                    if direction == "BUY":
                        stop = price - current_atr
                        target1 = price + current_atr * 1.5
                        target2 = price + current_atr * 1.5
                    else:
                        stop = price + current_atr
                        target1 = price - current_atr * 1.5
                        target2 = price - current_atr * 1.5

        price = float(frame["close"].iloc[i])
        high = float(frame["high"].iloc[i])
        low = float(frame["low"].iloc[i])
        if position:
            position["current_bar"] = i
            closed, exit_price, reason, partial_units = backtest_engine._manage_position(
                position, price, high, low, direction, i, max_hold,
            )
            if partial_units:
                capital += _append_exit(
                    trades, position, exit_price, "target1_partial", partial_units,
                    frame.index[i], commission, slippage, spread,
                )
                partial_ratio = partial_units / position["units"]
                position["units"] -= partial_units
                position["entry_commission"] -= position["entry_commission"] * partial_ratio
                position["slippage_cost"] -= position["slippage_cost"] * partial_ratio
                position["spread_cost"] -= position["spread_cost"] * partial_ratio
            if closed:
                capital += _append_exit(
                    trades, position, exit_price, reason, position["units"],
                    frame.index[i], commission, slippage, spread,
                )
                last_close_bar = i
                position = None

        if position is None and direction and stop and target1 and target2 and i != last_close_bar:
            fill = backtest_engine._fill_price(price, direction, slippage, spread)
            risk_scalar = backtest_engine._vol_scalar(
                float(range_atr.iloc[i]) if np.isfinite(range_atr.iloc[i]) else price * 0.01,
                range_atr,
                i,
            )
            risk_amount = capital * 0.01 * risk_scalar
            risk_per_unit = abs(fill - stop)
            units = risk_amount / risk_per_unit if risk_per_unit > 0 else 0
            if units > 0:
                entry_commission = fill * units * commission
                capital -= entry_commission
                position = {
                    "type": direction,
                    "fill": fill,
                    "stop_loss": stop,
                    "target1": target1,
                    "target2": target2,
                    "units": units,
                    "bar_index": i,
                    "current_bar": i,
                    "entry_commission": entry_commission,
                    "slippage_cost": abs(fill - price) * units,
                    "spread_cost": price * spread / 2 * units,
                    "partial_taken": False,
                    "entry_range_low": entry_low,
                    "entry_range_high": entry_high,
                    "bullish_probability": bull_probability,
                    "model_outputs": member_outputs,
                }

        equity.append(round(capital, 2))

    if position:
        position["current_bar"] = len(frame) - 1
        last_price = float(frame["close"].iloc[-1])
        capital += _append_exit(
            trades, position, last_price, "end_of_data", position["units"],
            frame.index[-1], commission, slippage, spread,
        )
        equity.append(round(capital, 2))

    result = backtest_engine._compute_stats(
        trades, equity, initial_capital, commission, slippage, timeframe, spread,
    )
    result["reproducibility"] = build_reproducibility_metadata(
        frame,
        strategy=AI_INSIGHTS_STRATEGY["key"],
        timeframe=timeframe,
        initial_capital=initial_capital,
        commission=commission,
        slippage=slippage,
        spread=spread,
        extra_config={
            "ai_model_version": AI_MODEL_VERSION,
            "direction_threshold": _DIRECTION_THRESHOLD,
            "triple_barrier_atr_multiple": _TB_ATR_MULT,
            "triple_barrier_max_hold": _TB_MAX_HOLD,
            "retrain_every": retrain_every,
            "entry_zone": "close +/- recent_20_bar_range_mean * (0.05..0.35)",
            "levels": {"stop_atr": 1.0, "target_atr": 1.5},
        },
        engine_version=AI_INSIGHTS_ENGINE_VERSION,
        model_version=AI_MODEL_VERSION,
    )
    result["ai_diagnostics"] = {
        "prediction_count": prediction_count,
        "model_checkpoints": model_checkpoints,
        "retrain_every": retrain_every,
        "direction_counts": direction_counts,
        "threshold": _DIRECTION_THRESHOLD,
        "training_label": "triple_barrier",
        "entry_fill_assumption": "market at signal close; entry zone retained as guidance",
    }
    return result
