"""Regression coverage for prediction cache freshness after evaluation."""
from datetime import datetime, timedelta

import pandas as pd


def test_evaluating_prediction_invalidates_its_history_context_cache(app, monkeypatch):
    with app.app_context():
        from app.extensions import cache, db
        from app.models.asset import Asset
        from app.models.prediction import Prediction
        from app.tasks.data_tasks import evaluate_expired_predictions

        asset = Asset(symbol="CACHEFRESH", name="Cache Freshness", market="crypto", is_active=True)
        db.session.add(asset)
        db.session.flush()
        prediction = Prediction(
            asset_id=asset.id,
            timeframe="1h",
            model_name="ensemble+cal",
            predicted_direction="bullish",
            bullish_probability=70,
            bearish_probability=30,
            confidence=70,
            entry_price=100,
            predicted_at=datetime.utcnow() - timedelta(hours=2),
            valid_until=datetime.utcnow() - timedelta(minutes=1),
        )
        db.session.add(prediction)
        db.session.commit()

        cache_key = f"prediction_history_context:{asset.id}:1h"
        cache.set(cache_key, {"sample_size": 0}, timeout=600)
        monkeypatch.setattr(
            "app.services.data.fetcher.market_fetcher.fetch",
            lambda *_args, **_kwargs: pd.DataFrame({"close": [101.0]}),
        )

        evaluate_expired_predictions(app)

        assert cache.get(cache_key) is None
        assert prediction.actual_direction == "bullish"
        assert prediction.was_correct is True
