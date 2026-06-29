from datetime import datetime
from app.extensions import db


class Prediction(db.Model):
    __tablename__ = "predictions"

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)
    model_name = db.Column(db.String(50))  # random_forest, xgboost, lgbm, lstm, ensemble
    bullish_probability = db.Column(db.Float)
    bearish_probability = db.Column(db.Float)
    predicted_direction = db.Column(db.String(10))  # bullish, bearish, neutral
    predicted_target = db.Column(db.Float)
    predicted_stop = db.Column(db.Float)
    confidence = db.Column(db.Float)
    features_used = db.Column(db.JSON, default=list)
    predicted_at = db.Column(db.DateTime, default=datetime.utcnow)
    valid_until = db.Column(db.DateTime)

    # Outcome tracking
    actual_direction = db.Column(db.String(10))
    was_correct = db.Column(db.Boolean)
    evaluated_at = db.Column(db.DateTime)

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
            "confidence": self.confidence,
            "predicted_at": self.predicted_at.isoformat(),
        }
