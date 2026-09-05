"""Regression tests for the AI prediction validation context contract."""
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def premium_headers(app):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, Subscription, User
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="premium").first()
        subscription = Subscription.query.filter_by(name="premium").first()
        user = User(
            username="predictioncontext",
            email="predictioncontext@example.com",
            role_id=role.id,
            subscription_id=subscription.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}


def test_cached_prediction_includes_bounded_historical_context(app, client, premium_headers):
    with app.app_context():
        from app.extensions import db
        from app.models.asset import Asset
        from app.models.prediction import Prediction

        asset = Asset(symbol="CTXASSET", name="Context Asset", market="crypto", is_active=True)
        db.session.add(asset)
        db.session.flush()
        now = datetime.utcnow()
        db.session.add_all([
            Prediction(
                asset_id=asset.id, timeframe="1h", model_name="ensemble+cal",
                predicted_direction="bullish", bullish_probability=70,
                bearish_probability=30, confidence=70, entry_price=100,
                predicted_at=now - timedelta(minutes=5), evaluated_at=now - timedelta(minutes=1),
                was_correct=True,
            ),
            Prediction(
                asset_id=asset.id, timeframe="1h", model_name="ensemble+cal",
                predicted_direction="bearish", bullish_probability=30,
                bearish_probability=70, confidence=70, entry_price=100,
                predicted_at=now - timedelta(minutes=10), evaluated_at=now - timedelta(minutes=2),
                was_correct=False,
            ),
        ])
        db.session.commit()
        asset_id = asset.id

    response = client.get(f"/api/v1/predictions/{asset_id}?timeframe=1h", headers=premium_headers)

    assert response.status_code == 200
    context = response.get_json()["historical_context"]
    assert context["sample_size"] == 2
    assert context["correct"] == 1
    assert context["accuracy"] == 50.0
    assert context["scope"] == "same asset and timeframe, recent resolved predictions"
