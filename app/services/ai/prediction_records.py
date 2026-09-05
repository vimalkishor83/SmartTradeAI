"""Build persisted prediction rows from the AI predictor contract."""

from datetime import datetime

from app.models.prediction import Prediction


def build_prediction_record(
    *,
    asset_id: int,
    timeframe: str,
    result: dict,
    entry_price: float,
    valid_until: datetime,
) -> Prediction:
    """Map one predictor result into the canonical database representation."""
    return Prediction(
        asset_id=asset_id,
        timeframe=timeframe,
        model_name=result["model_name"],
        model_version=result.get("model_version"),
        bullish_probability=result["bullish_probability"],
        bearish_probability=result["bearish_probability"],
        predicted_direction=result["predicted_direction"],
        predicted_target=result.get("predicted_target"),
        predicted_stop=result.get("predicted_stop"),
        entry_price=entry_price,
        confidence=result["confidence"],
        valid_until=valid_until,
    )
