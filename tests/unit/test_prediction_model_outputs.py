"""Tests for truthful ensemble-member probability output."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time

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

    assert result["model_version"] == "ensemble-calibrated-v2"
    assert result["model_outputs"] == {"random_forest": 60.0, "xgboost": 64.0}


def test_model_artifact_path_changes_with_training_contract(monkeypatch):
    original_path = predictor_module._model_path("rf_SYMBOL_1h")
    monkeypatch.setattr(predictor_module, "AI_MODEL_VERSION", "test-contract-v3")

    assert predictor_module._model_path("rf_SYMBOL_1h") != original_path


def test_model_save_publishes_completed_artifact_atomically(monkeypatch, tmp_path):
    import joblib

    target = tmp_path / "artifact.pkl"
    monkeypatch.setattr(predictor_module, "_model_path", lambda _key: target)
    replacements = []
    real_replace = predictor_module.os.replace

    def record_replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        return real_replace(source, destination)

    monkeypatch.setattr(predictor_module.os, "replace", record_replace)

    predictor_module._save_model("artifact", {"value": 42})

    assert joblib.load(target) == {"value": 42}
    assert len(replacements) == 1
    source, destination = replacements[0]
    assert source.parent == target.parent
    assert source != target
    assert destination == target
    assert not source.exists()


def test_model_save_cleans_temporary_artifact_after_serialization_failure(
    monkeypatch, tmp_path,
):
    import joblib

    target = tmp_path / "artifact.pkl"
    target.write_bytes(b"existing-artifact")
    monkeypatch.setattr(predictor_module, "_model_path", lambda _key: target)

    def fail_dump(_model, _path):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(joblib, "dump", fail_dump)
    predictor_module._save_model("artifact", {"value": 42})

    assert target.read_bytes() == b"existing-artifact"
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


def test_prediction_cache_collapses_concurrent_misses(monkeypatch):
    predictor = AIPredictor()
    predictor.invalidate_cache()
    frame = pd.DataFrame({
        "high": [101.0] * 120,
        "low": [99.0] * 120,
        "close": [100.0] * 120,
    })
    features = pd.DataFrame(
        np.ones((120, 2)), index=frame.index, columns=["feature_a", "feature_b"],
    )
    monkeypatch.setattr(predictor_module, "_build_features", lambda _df: features)
    monkeypatch.setattr(predictor_module, "_models_ready", lambda _key: False)
    monkeypatch.setattr(
        predictor_module,
        "_make_triple_barrier_labels",
        lambda data, _atr: pd.Series(np.zeros(len(data)), index=data.index),
    )

    calls = 0
    calls_lock = threading.Lock()

    def fake_ensemble(_x_train, _y_train, _x_pred, _symbol, _timeframe):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return 0.62, {"random_forest": 0.62}

    monkeypatch.setattr(predictor, "_ensemble_predict", fake_ensemble)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda _index: predictor.predict(frame, "SINGLEFLIGHT", "1h"),
                range(2),
            ))
    finally:
        predictor.invalidate_cache("SINGLEFLIGHT", "1h")

    assert calls == 1
    assert results[0]["bullish_probability"] == results[1]["bullish_probability"] == 62.0
    assert results[0]["model_outputs"] == results[1]["model_outputs"] == {
        "random_forest": 62.0,
    }
