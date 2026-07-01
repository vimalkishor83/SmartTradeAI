from flask import Blueprint, request, jsonify
from app.models.asset import Asset
from app.models.prediction import Prediction
from app.extensions import db
from app.auth.decorators import login_required, premium_required
from app.services.ai.predictor import ai_predictor
from app.services.data.fetcher import market_fetcher
from datetime import datetime, timedelta

predictions_bp = Blueprint("predictions", __name__)


@predictions_bp.route("/<int:asset_id>", methods=["GET"])
@premium_required
def get_prediction(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    timeframe = request.args.get("timeframe", "1h")

    # Return cached prediction if recent
    existing = Prediction.query.filter_by(
        asset_id=asset_id, timeframe=timeframe
    ).filter(Prediction.predicted_at >= datetime.utcnow() - timedelta(minutes=30)).first()

    if existing:
        return jsonify(existing.to_dict()), 200

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
