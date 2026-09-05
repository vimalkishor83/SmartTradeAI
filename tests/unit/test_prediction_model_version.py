"""Tests for prediction model-version persistence and serialization."""

from datetime import datetime

from app.models.prediction import Prediction
from app.services.ai.prediction_records import build_prediction_record


def _result(model_version="ensemble-calibrated-v1"):
    return {
        "model_name": "ensemble+cal",
        "model_version": model_version,
        "bullish_probability": 65.0,
        "bearish_probability": 35.0,
        "predicted_direction": "bullish",
        "predicted_target": 105.0,
        "predicted_stop": 98.0,
        "confidence": 65.0,
    }


def test_prediction_record_maps_model_version_from_predictor_result():
    prediction = build_prediction_record(
        asset_id=7,
        timeframe="1h",
        result=_result(),
        entry_price=100.0,
        valid_until=datetime(2026, 9, 6, 12, 0),
        data_quality={"status": "GREEN", "candle_count": 220},
    )

    assert prediction.model_version == "ensemble-calibrated-v1"
    prediction.model_outputs = {"random_forest": 62.0, "xgboost": 68.0}
    assert prediction.to_dict()["model_version"] == "ensemble-calibrated-v1"
    assert prediction.to_dict()["data_quality"]["status"] == "GREEN"
    assert prediction.to_dict()["model_outputs"]["xgboost"] == 68.0


def test_legacy_prediction_serializes_missing_model_version_explicitly():
    prediction = Prediction(
        asset_id=7,
        timeframe="1h",
        model_name="ensemble",
        predicted_at=datetime(2026, 9, 6, 12, 0),
    )

    assert prediction.to_dict()["model_version"] is None
    assert prediction.to_dict()["data_quality"] is None
    assert prediction.to_dict()["model_outputs"] is None
