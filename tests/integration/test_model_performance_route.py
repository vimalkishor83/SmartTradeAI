"""Regression tests for the database-backed model performance summary."""
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def login_headers(app):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, Subscription, User
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="premium").first()
        subscription = Subscription.query.filter_by(name="premium").first()
        user = User(
            username="modelperformance",
            email="modelperformance@example.com",
            role_id=role.id,
            subscription_id=subscription.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}


def test_model_performance_aggregates_without_loading_prediction_rows(
    app, client, login_headers,
):
    with app.app_context():
        from app.extensions import cache, db
        from app.models.asset import Asset
        from app.models.prediction import Prediction

        cache.delete("model_perf_stats")
        now = datetime.utcnow()
        asset_a = Asset(symbol="PERFA", name="Performance A", market="crypto", is_active=True)
        asset_b = Asset(symbol="PERFB", name="Performance B", market="crypto", is_active=True)
        db.session.add_all([asset_a, asset_b])
        db.session.flush()
        db.session.add_all([
            Prediction(
                asset_id=asset_a.id, timeframe="1h", model_name="rf",
                model_version="ensemble-calibrated-v1",
                predicted_direction="bullish", was_correct=True,
                evaluated_at=now - timedelta(days=1),
            ),
            Prediction(
                asset_id=asset_a.id, timeframe="1h", model_name="rf",
                model_version="ensemble-calibrated-v1",
                predicted_direction="bearish", was_correct=False,
                evaluated_at=now - timedelta(days=2),
            ),
            Prediction(
                asset_id=asset_b.id, timeframe="4h", model_name=None,
                predicted_direction="bullish", was_correct=True,
                evaluated_at=now - timedelta(days=31),
            ),
            Prediction(
                asset_id=asset_b.id, timeframe="4h", model_name="ignored",
                predicted_direction="bullish", was_correct=None,
                evaluated_at=now - timedelta(days=1),
            ),
        ])
        db.session.commit()

    response = client.get("/api/v1/predictions/model-performance", headers=login_headers)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["overall"] == {"total": 3, "correct": 2, "accuracy": 66.7}
    assert payload["coverage"] == {
        "evaluated": 3,
        "versioned": 2,
        "legacy": 1,
        "versioned_pct": 66.7,
        "versioned_accuracy": 50.0,
    }
    assert payload["by_timeframe"] == {
        "1h": {"total": 2, "correct": 1, "accuracy": 50.0},
        "4h": {"total": 1, "correct": 1, "accuracy": 100.0},
    }
    assert payload["by_model"] == {
        "rf": {"total": 2, "correct": 1, "accuracy": 50.0},
        "unknown": {"total": 1, "correct": 1, "accuracy": 100.0},
    }
    assert payload["by_model_version"] == {
        "ensemble-calibrated-v1": {"total": 2, "correct": 1, "accuracy": 50.0},
        "legacy/unspecified": {"total": 1, "correct": 1, "accuracy": 100.0},
    }
    assert [row["symbol"] for row in payload["by_asset"]] == ["PERFA", "PERFB"]
    assert payload["by_asset"][0]["total"] == 2
    assert payload["by_asset"][1]["total"] == 1
    assert len(payload["trend"]) == 2
    assert all(row["date"] >= (now - timedelta(days=30)).date().isoformat() for row in payload["trend"])


def test_empty_model_performance_is_cached_contract(app, client, login_headers):
    with app.app_context():
        from app.extensions import cache

        cache.delete("model_perf_stats")

    response = client.get("/api/v1/predictions/model-performance", headers=login_headers)

    assert response.status_code == 200
    assert response.get_json() == {
        "overall": {"total": 0, "correct": 0, "accuracy": 0},
        "coverage": {
            "evaluated": 0,
            "versioned": 0,
            "legacy": 0,
            "versioned_pct": 0,
            "versioned_accuracy": None,
        },
        "by_timeframe": {},
        "by_asset": [],
        "by_model": {},
        "by_model_version": {},
        "trend": [],
    }
