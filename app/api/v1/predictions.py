from flask import Blueprint, request, jsonify
from app.models.asset import Asset
from app.models.prediction import Prediction
from app.extensions import db, cache, limiter
from app.auth.decorators import login_required, premium_required, subscription_feature_required
from app.services.ai.predictor import ai_predictor
from app.services.ai.prediction_records import build_prediction_record
from app.services.data.fetcher import market_fetcher
from app.services.data.quality import assess_data_quality
from app.services.backtest.validation import parse_timeframe
from sqlalchemy import case, func
from datetime import datetime, timedelta

predictions_bp = Blueprint("predictions", __name__)


def _prediction_history_summary(rows) -> dict:
    """Summarize recent resolved predictions without implying a guarantee."""
    total = len(rows)
    correct = sum(1 for row in rows if row.was_correct)
    return {
        "sample_size": total,
        "correct": correct,
        "accuracy": round(correct / total * 100, 1) if total else None,
        "scope": "same asset and timeframe, recent resolved predictions",
    }


def _prediction_history_context(asset_id: int, timeframe: str) -> dict:
    """Return a bounded validation context for an AI Insights card."""
    cache_key = f"prediction_history_context:{asset_id}:{timeframe}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    rows = (Prediction.query
            .filter_by(asset_id=asset_id, timeframe=timeframe)
            .filter(Prediction.was_correct.isnot(None))
            .order_by(Prediction.evaluated_at.desc())
            .limit(50)
            .all())
    summary = _prediction_history_summary(rows)
    cache.set(cache_key, summary, timeout=600)
    return summary


def _prediction_response(prediction: Prediction) -> dict:
    payload = prediction.to_dict()
    payload["historical_context"] = _prediction_history_context(
        prediction.asset_id, prediction.timeframe,
    )
    return payload


@predictions_bp.route("/<int:asset_id>", methods=["GET"])
@premium_required
@subscription_feature_required("ai_enabled")
@limiter.limit("30 per minute;200 per hour")
def get_prediction(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    try:
        timeframe = parse_timeframe(request.args.get("timeframe"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Return cached prediction if recent
    existing = Prediction.query.filter_by(
        asset_id=asset_id, timeframe=timeframe
    ).filter(
        Prediction.predicted_at >= datetime.utcnow() - timedelta(minutes=30),
    ).order_by(Prediction.predicted_at.desc()).first()

    if existing:
        return jsonify(_prediction_response(existing)), 200

    # ── Non-blocking: never train a model inside a user request ──────────────
    # Training a cold model takes ~100s and would hang the AI Insights page
    # (which fires several of these in parallel). Predictions are produced by
    # the background `prewarm_ai_cache` job and cached above. If none is ready
    # yet, return a fast "warming up" response so the UI shows a neutral
    # placeholder instead of blocking. The prediction appears on the next poll
    # once the background job (or an already-cached model) fills it in.
    if not ai_predictor.has_ready_model(asset.symbol, timeframe):
        return jsonify({
            "asset_id":            asset.id,
            "timeframe":           timeframe,
            "model_name":          "warming_up",
            "model_version":       None,
            "model_outputs":       {},
            "predicted_direction": "neutral",
            "bullish_probability": 50.0,
            "bearish_probability": 50.0,
            "confidence":          0.0,
            "predicted_target":    None,
            "predicted_stop":      None,
            "warming_up":          True,
        }), 202

    df = market_fetcher.fetch(asset, timeframe, 220)
    if df is None:
        return jsonify({"error": "Data unavailable"}), 503

    data_quality = assess_data_quality(df, asset.market, timeframe)
    result = ai_predictor.predict(df, asset.symbol, timeframe)

    # A neutral fallback is not a trained prediction and must not enter the
    # validation history as though a model produced it.
    if not result.get("model_version"):
        return jsonify({
            "asset_id": asset.id,
            "timeframe": timeframe,
            **result,
            "data_quality": data_quality,
            "warming_up": True,
        }), 202

    pred = build_prediction_record(
        asset_id=asset.id,
        timeframe=timeframe,
        result=result,
        entry_price=float(df["close"].iloc[-1]),
        valid_until=datetime.utcnow() + timedelta(hours=4),
        data_quality=data_quality,
    )
    db.session.add(pred)
    db.session.commit()

    return jsonify(_prediction_response(pred)), 200


def _empty_model_performance() -> dict:
    return {
        "overall": {"total": 0, "correct": 0, "accuracy": 0},
        "coverage": {
            "evaluated": 0,
            "versioned": 0,
            "legacy": 0,
            "versioned_pct": 0,
            "versioned_accuracy": None,
        },
        "by_timeframe": {},
        "by_asset": [],
        "by_model": {},
        "by_model_version": {},
        "trend": [],
    }


def _correct_count_expr():
    """Build a portable SQL expression for boolean prediction outcomes."""
    return func.coalesce(
        func.sum(case((Prediction.was_correct.is_(True), 1), else_=0)),
        0,
    )


@predictions_bp.route("/model-performance", methods=["GET"])
@login_required
def model_performance():
    """
    Aggregate accuracy stats for the model performance dashboard.
    Returns per-asset × per-timeframe accuracy, overall stats, and a
    rolling 30-day accuracy trend (daily buckets).

    All aggregation happens in the database. The previous implementation
    hydrated every evaluated prediction into Python before calculating five
    views, which made response memory and latency grow with table size.
    """
    cached = cache.get("model_perf_stats")
    if cached is not None:
        return jsonify(cached), 200

    resolved = Prediction.was_correct.isnot(None)
    overall_row = (db.session.query(
        func.count(Prediction.id).label("total"),
        _correct_count_expr().label("correct"),
    ).filter(resolved).one())
    total = int(overall_row.total or 0)
    correct = int(overall_row.correct or 0)

    if not total:
        payload = _empty_model_performance()
        cache.set("model_perf_stats", payload, timeout=600)
        return jsonify(payload), 200

    # Versioned rows are the auditable model population. Older rows can still
    # be useful for continuity, but must not look equivalent to current,
    # reproducible model output in the dashboard.
    versioned_expr = func.nullif(Prediction.model_version, "").isnot(None)
    versioned_row = (db.session.query(
        func.count(Prediction.id).label("total"),
        _correct_count_expr().label("correct"),
    ).filter(resolved, versioned_expr).one())
    versioned_total = int(versioned_row.total or 0)
    versioned_correct = int(versioned_row.correct or 0)
    coverage = {
        "evaluated": total,
        "versioned": versioned_total,
        "legacy": max(0, total - versioned_total),
        "versioned_pct": round(versioned_total / total * 100, 1) if total else 0,
        "versioned_accuracy": (
            round(versioned_correct / versioned_total * 100, 1)
            if versioned_total else None
        ),
    }

    by_timeframe = {}
    timeframe_rows = (db.session.query(
        Prediction.timeframe.label("timeframe"),
        func.count(Prediction.id).label("total"),
        _correct_count_expr().label("correct"),
    ).filter(resolved)
     .group_by(Prediction.timeframe)
     .order_by(Prediction.timeframe.asc())
     .all())
    for row in timeframe_rows:
        row_total = int(row.total or 0)
        row_correct = int(row.correct or 0)
        by_timeframe[row.timeframe] = {
            "total": row_total,
            "correct": row_correct,
            "accuracy": round(row_correct / row_total * 100, 1) if row_total else 0,
        }

    # Ask the database for only the top 20 assets before loading display names.
    asset_rows = (db.session.query(
        Prediction.asset_id.label("asset_id"),
        func.count(Prediction.id).label("total"),
        _correct_count_expr().label("correct"),
    ).filter(resolved)
     .group_by(Prediction.asset_id)
     .order_by(func.count(Prediction.id).desc(), Prediction.asset_id.asc())
     .limit(20)
     .all())
    asset_ids = [row.asset_id for row in asset_rows]
    assets_map = {}
    if asset_ids:
        assets_map = {a.id: a for a in Asset.query.filter(Asset.id.in_(asset_ids)).all()}

    by_asset = []
    for row in asset_rows:
        asset = assets_map.get(row.asset_id)
        if not asset:
            continue
        row_total = int(row.total or 0)
        row_correct = int(row.correct or 0)
        by_asset.append({
            "asset_id": row.asset_id,
            "symbol": asset.symbol,
            "name": asset.name,
            "market": asset.market,
            "total": row_total,
            "correct": row_correct,
            "accuracy": round(row_correct / row_total * 100, 1) if row_total else 0,
        })

    model_expr = func.coalesce(func.nullif(Prediction.model_name, ""), "unknown")
    by_model = {}
    model_rows = (db.session.query(
        model_expr.label("model"),
        func.count(Prediction.id).label("total"),
        _correct_count_expr().label("correct"),
    ).filter(resolved)
     .group_by(model_expr)
     .order_by(model_expr.asc())
     .all())
    for row in model_rows:
        row_total = int(row.total or 0)
        row_correct = int(row.correct or 0)
        by_model[row.model] = {
            "total": row_total,
            "correct": row_correct,
            "accuracy": round(row_correct / row_total * 100, 1) if row_total else 0,
        }

    version_expr = func.coalesce(
        func.nullif(Prediction.model_version, ""), "legacy/unspecified"
    )
    by_model_version = {}
    version_rows = (db.session.query(
        version_expr.label("model_version"),
        func.count(Prediction.id).label("total"),
        _correct_count_expr().label("correct"),
    ).filter(resolved)
     .group_by(version_expr)
     .order_by(version_expr.asc())
     .all())
    for row in version_rows:
        row_total = int(row.total or 0)
        row_correct = int(row.correct or 0)
        by_model_version[row.model_version] = {
            "total": row_total,
            "correct": row_correct,
            "accuracy": round(row_correct / row_total * 100, 1) if row_total else 0,
        }

    # Group only the 30-day window needed by the chart instead of transferring
    # the complete history just to discard older rows in Python.
    cutoff = datetime.utcnow() - timedelta(days=30)
    day_expr = func.date(Prediction.evaluated_at)
    trend_rows = (db.session.query(
        day_expr.label("day"),
        func.count(Prediction.id).label("total"),
        _correct_count_expr().label("correct"),
    ).filter(
        resolved,
        Prediction.evaluated_at.isnot(None),
        Prediction.evaluated_at >= cutoff,
    ).group_by(day_expr).order_by(day_expr.asc()).all())
    trend = []
    for row in trend_rows:
        row_total = int(row.total or 0)
        row_correct = int(row.correct or 0)
        day = row.day.date() if isinstance(row.day, datetime) else row.day
        trend.append({
            "date": day.isoformat() if hasattr(day, "isoformat") else str(day),
            "total": row_total,
            "correct": row_correct,
            "accuracy": round(row_correct / row_total * 100, 1) if row_total else 0,
        })

    payload = {
        "overall": {
            "total": total,
            "correct": correct,
            "accuracy": round(correct / total * 100, 1) if total else 0,
        },
        "coverage": coverage,
        "by_timeframe": by_timeframe,
        "by_asset": by_asset,
        "by_model": by_model,
        "by_model_version": by_model_version,
        "trend": trend,
    }
    cache.set("model_perf_stats", payload, timeout=600)
    return jsonify(payload), 200
