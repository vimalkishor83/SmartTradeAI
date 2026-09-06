import pytest


@pytest.fixture
def analysis_headers(app):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, User
        from app.models.asset import Asset
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="free").first()
        asset = Asset(symbol="ADVTEST", name="Advanced Test", market="crypto", is_active=True)
        user = User(
            username="advancedvalidation",
            email="advancedvalidation@example.com",
            role_id=role.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add_all([asset, user])
        db.session.commit()
        asset_id = asset.id
        token = create_access_token(identity=str(user.id))

    return {"Authorization": f"Bearer {token}"}, asset_id


@pytest.mark.parametrize("timeframe", ["", "1w", "<script>"])
def test_advanced_analysis_rejects_unsupported_timeframes(client, analysis_headers, timeframe):
    headers, asset_id = analysis_headers
    response = client.get(
        f"/api/v1/market-data/{asset_id}/advanced",
        headers=headers,
        query_string={"timeframe": timeframe},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] in {"Unsupported timeframe", "timeframe must be a string"}


def test_advanced_analysis_accepts_supported_timeframe_without_external_fetch(client, analysis_headers, monkeypatch):
    headers, asset_id = analysis_headers
    from app.api.v1 import market_data

    monkeypatch.setattr(market_data.market_fetcher, "fetch", lambda *args, **kwargs: None)
    response = client.get(
        f"/api/v1/market-data/{asset_id}/advanced",
        headers=headers,
        query_string={"timeframe": "1h"},
    )

    assert response.status_code == 503
    assert response.get_json()["error"] == "Insufficient data"
