from datetime import datetime
from app.extensions import db


class Prediction(db.Model):
    __tablename__ = "predictions"

    id = db.Column(db.Integer, primary_key=True)
    # Composite index: get_prediction() (app/api/v1/predictions.py) filters
    # on exactly (asset_id, timeframe, predicted_at range) on every call to
    # a frequently-hit endpoint. Signal has an equivalent index
    # (idx_signals_asset_tf) for the same pattern; Prediction didn't.
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False, index=True)
    timeframe = db.Column(db.String(10), nullable=False, index=True)
    model_name = db.Column(db.String(50))  # random_forest, xgboost, lgbm, lstm, ensemble
    bullish_probability = db.Column(db.Float)
    bearish_probability = db.Column(db.Float)
    predicted_direction = db.Column(db.String(10))  # bullish, bearish, neutral
    predicted_target = db.Column(db.Float)
    predicted_stop = db.Column(db.Float)
    # The actual close price at the moment the prediction was made — the
    # correct reference point for evaluating accuracy later. Previously
    # missing entirely; evaluate_expired_predictions() fell back to using
    # predicted_target/predicted_stop as a proxy "entry price", which isn't
    # what those fields represent and skewed reported model accuracy.
    entry_price = db.Column(db.Float)
    confidence = db.Column(db.Float)
    features_used = db.Column(db.JSON, default=list)
    predicted_at = db.Column(db.DateTime, default=datetime.utcnow)
    valid_until = db.Column(db.DateTime)

    # Outcome tracking
    actual_direction = db.Column(db.String(10))
    was_correct = db.Column(db.Boolean)
    evaluated_at = db.Column(db.DateTime)

    __table_args__ = (
        # The two hottest prediction reads both filter on
        # (asset_id, timeframe, predicted_at >= cutoff): get_prediction()
        # (one asset, per asset-detail/AI-insights view) and ai_summary /
        # prewarm_ai (asset_id.in_, timeframe.in_, predicted_at >= cutoff).
        # A single composite index seeks straight to the recent row(s)
        # instead of leaning on the separate asset_id / timeframe indexes.
        db.Index("idx_predictions_asset_tf_time", "asset_id", "timeframe", "predicted_at"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "timeframe": self.timeframe,
            "model_name": self.model_name,
            "bullish_probability": self.bullish_probability,
            "bearish_probability": self.bearish_probability,
            "predicted_direction": self.predicted_direction,
            "predicted_target": self.predicted_target,
            "entry_price": self.entry_price,
            "confidence": self.confidence,
            "predicted_at": self.predicted_at.isoformat(),
        }
