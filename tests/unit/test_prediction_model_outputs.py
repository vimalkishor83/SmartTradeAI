"""Tests for truthful ensemble-member probability output."""

import numpy as np
import pandas as pd
import pytest

from app.services.ai import predictor as predictor_module
from app.services.ai.predictor import AIPredictor


class _FakeModel:
    def __init__(self, bullish_probability):
        self.bullish_probability = bullish_probability

    def predict_proba(self, _features):
        return np.array([[1.0 - self.bullish_probability, self.bullish_probability]])


def test_inference_only_returns_real_member_probabilities(monkeypatch):
    models = {
        "rf_BTCUSDT_1h": _FakeModel(0.52),
        "xgb_BTCUSDT_1h": _FakeModel(0.64),
        "lgb_BTCUSDT_1h": _FakeModel(0.58),
    }
    monkeypatch.setattr(predictor_module, "_load_model", models.get)

    result = AIPredictor()._ensemble_predict_inference_only(
        np.array([[1.0, 2.0]]), "BTCUSDT_1h",
    )

    assert result is not None
    probability, members = result
    assert probability == pytest.approx(0.58)
    assert members == {
        "random_forest": 0.52,
        "xgboost": 0.64,
        "lightgbm": 0.58,
    }


def test_prediction_cache_keeps_member_outputs_on_fast_path():
    predictor = AIPredictor()
    cache_key = "CACHEASSET_1h"
    with predictor._cache_lock:
        predictor._pred_cache[cache_key] = (
            0.62,
            {"random_forest": 0.60, "xgboost": 0.64},
            9999999999.0,
        )

    try:
        frame = pd.DataFrame({
            "high": [101.0] * 100,
            "low": [99.0] * 100,
            "close": [100.0] * 100,
        })
        result = predictor.predict(frame, "CACHEASSET", "1h")
    finally:
        predictor.invalidate_cache("CACHEASSET", "1h")

    assert result["model_version"] == "ensemble-calibrated-v1"
    assert result["model_outputs"] == {"random_forest": 60.0, "xgboost": 64.0}
