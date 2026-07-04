from flask import Blueprint, request, jsonify
from app.models.asset import Asset
from app.models.prediction import Prediction
from app.extensions import db, cache, limiter
from app.auth.decorators import login_required, premium_required
from app.services.ai.predictor import ai_predictor
from app.services.data.fetcher import market_fetcher
from sqlalchemy import func
from datetime import datetime, timedelta

predictions_bp = Blueprint("predictions", __name__)


@predictions_bp.route("/<int:asset_id>", methods=["GET"])
@premium_required
@limiter.limit("30 per minute;200 per hour")
def get_prediction(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    timeframe = request.args.get("timeframe", "1h")

    # Return cached prediction if recent
    existing = Prediction.query.filter_by(
        asset_id=asset_id, timeframe=timeframe
    ).filter(Prediction.predicted_at >= datetime.utcnow() - timedelta(minutes=30)).first()

    if existing:
        return jsonify(existing.to_dict()), 200

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

    result = ai_predictor.predict(df, asset.symbol, timeframe)

    pred = Prediction(
        asset_id=asset.id,
        timeframe=timeframe,
        model_name=result["model_name"],
        bullish_probability=result["bullish_probability"],
        bearish_probability=result["bearish_probability"],
        predicted_direction=result["predicted_direction"],
        predicted_target=result["predicted_target"],
        predicted_stop=result["predicted_stop"],
        confidence=result["confidence"],
        valid_until=datetime.utcnow() + timedelta(hours=4),
    )
    db.session.add(pred)
    db.session.commit()

    return jsonify(pred.to_dict()), 200


@predictions_bp.route("/model-performance", methods=["GET"])
@login_required
def model_performance():
    """
    Aggregate accuracy stats for the model performance dashboard.
    Returns per-asset × per-timeframe accuracy, overall stats, and a
    rolling 30-day accuracy trend (daily buckets).
    """
    cached = cache.get("model_perf_stats")
    if cached:
        return jsonify(cached), 200

    # Only count evaluated predictions (was_correct is not null)
    evaluated = Prediction.query.filter(Prediction.was_correct != None).all()

    if not evaluated:
        return jsonify({
            "overall": {"total": 0, "correct": 0, "accuracy": 0},
            "by_timeframe": {},
            "by_asset": [],
            "by_model": {},
            "trend": [],
        }), 200

    asset_ids = {p.asset_id for p in evaluated}
    assets_map = {a.id: a for a in Asset.query.filter(Asset.id.in_(asset_ids)).all()}

    # Overall
    total   = len(evaluated)
    correct = sum(1 for p in evaluated if p.was_correct)
    acc_pct = round(correct / total * 100, 1) if total else 0

    # By timeframe
    tf_stats: dict[str, dict] = {}
    for p in evaluated:
        tf = p.timeframe
        if tf not in tf_stats:
            tf_stats[tf] = {"total": 0, "correct": 0}
        tf_stats[tf]["total"] += 1
        if p.was_correct:
            tf_stats[tf]["correct"] += 1
    by_timeframe = {
        tf: {
            "total":    s["total"],
            "correct":  s["correct"],
            "accuracy": round(s["correct"] / s["total"] * 100, 1) if s["total"] else 0,
        }
        for tf, s in sorted(tf_stats.items())
    }

    # By asset (top 20 by sample count)
    asset_stats: dict[int, dict] = {}
    for p in evaluated:
        aid = p.asset_id
        if aid not in asset_stats:
            asset_stats[aid] = {"total": 0, "correct": 0}
        asset_stats[aid]["total"] += 1
        if p.was_correct:
            asset_stats[aid]["correct"] += 1
    by_asset = []
    for aid, s in sorted(asset_stats.items(), key=lambda x: -x[1]["total"])[:20]:
        a = assets_map.get(aid)
        if not a:
            continue
        by_asset.append({
            "asset_id": aid,
            "symbol":   a.symbol,
            "name":     a.name,
            "market":   a.market,
            "total":    s["total"],
            "correct":  s["correct"],
            "accuracy": round(s["correct"] / s["total"] * 100, 1) if s["total"] else 0,
        })

    # By model
    model_stats: dict[str, dict] = {}
    for p in evaluated:
        m = p.model_name or "unknown"
        if m not in model_stats:
            model_stats[m] = {"total": 0, "correct": 0}
        model_stats[m]["total"] += 1
        if p.was_correct:
            model_stats[m]["correct"] += 1
    by_model = {
        m: {
            "total":    s["total"],
            "correct":  s["correct"],
            "accuracy": round(s["correct"] / s["total"] * 100, 1) if s["total"] else 0,
        }
        for m, s in model_stats.items()
    }

    # 30-day daily trend
    cutoff = datetime.utcnow() - timedelta(days=30)
    recent = [p for p in evaluated if p.evaluated_at and p.evaluated_at >= cutoff]
    daily: dict[str, dict] = {}
    for p in recent:
        day = p.evaluated_at.strftime("%Y-%m-%d")
        if day not in daily:
            daily[day] = {"total": 0, "correct": 0}
        daily[day]["total"] += 1
        if p.was_correct:
            daily[day]["correct"] += 1
    trend = [
        {
            "date":     d,
            "total":    s["total"],
            "correct":  s["correct"],
            "accuracy": round(s["correct"] / s["total"] * 100, 1) if s["total"] else 0,
        }
        for d, s in sorted(daily.items())
    ]

    payload = {
        "overall":      {"total": total, "correct": correct, "accuracy": acc_pct},
        "by_timeframe": by_timeframe,
        "by_asset":     by_asset,
        "by_model":     by_model,
        "trend":        trend,
    }
    cache.set("model_perf_stats", payload, timeout=600)
    return jsonify(payload), 200
