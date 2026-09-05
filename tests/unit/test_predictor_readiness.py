"""Regression tests for the predictor's non-blocking readiness contract."""


def test_readiness_matches_all_member_inference_requirement(monkeypatch, tmp_path):
    import app.services.ai.predictor as predictor_module
    from app.services.ai.predictor import AIPredictor

    cache_key = "READINESS_1h"
    for prefix in ("rf_", "xgb_", "lgb_"):
        (tmp_path / f"{prefix}{cache_key}").touch()

    monkeypatch.setattr(
        predictor_module,
        "_model_path",
        lambda key: tmp_path / key,
    )
    monkeypatch.setattr(predictor_module, "_models_ready", lambda key: False)

    predictor = AIPredictor()
    predictor.invalidate_cache("READINESS", "1h")
    assert predictor.has_ready_model("READINESS", "1h") is False

    monkeypatch.setattr(predictor_module, "_models_ready", lambda key: True)
    assert predictor.has_ready_model("READINESS", "1h") is True
