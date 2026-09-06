"""Ensure cold summary caches are not scoped to the first request."""

import pytest


@pytest.fixture
def summary_headers(app):
    with app.app_context():
        from flask_jwt_extended import create_access_token
        from app.extensions import db
        from app.models.user import User, Role

        role = Role.query.filter_by(name="free").first()
        user = User(
            username="summaryscope",
            email="summaryscope@example.com",
            role_id=role.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def summary_assets(app):
    with app.app_context():
        from app.extensions import db
        from app.models.asset import Asset

        assets = [
            Asset(symbol="SCOPECRYPTO", name="Scope Crypto", market="crypto", exchange="scope"),
            Asset(symbol="SCOPEFOREX", name="Scope Forex", market="forex", exchange="scope"),
        ]
        db.session.add_all(assets)
        db.session.commit()
        return {asset.market: asset.id for asset in assets}


def test_ta_summary_cold_cache_keeps_the_full_active_universe(
    app, client, monkeypatch, summary_headers, summary_assets
):
    from app.api.v1 import market_data
    from app.extensions import cache

    monkeypatch.setattr(market_data, "blocked_data_markets", lambda: set())
    monkeypatch.setattr(market_data.market_fetcher, "fetch_many", lambda *args, **kwargs: {})
    with app.app_context():
        cache.clear()

    first = client.get(
        "/api/v1/market-data/ta-summary?market=crypto", headers=summary_headers
    )
    assert first.status_code == 200
    assert [row["id"] for row in first.get_json()["assets"]] == [summary_assets["crypto"]]

    second = client.get(
        "/api/v1/market-data/ta-summary?market=forex", headers=summary_headers
    )
    assert second.status_code == 200
    assert [row["id"] for row in second.get_json()["assets"]] == [summary_assets["forex"]]


def test_ema_summary_cold_cache_keeps_the_full_active_universe(
    app, client, monkeypatch, summary_headers, summary_assets
):
    from app.api.v1 import market_data
    from app.extensions import cache

    monkeypatch.setattr(market_data, "blocked_data_markets", lambda: set())
    monkeypatch.setattr(market_data.market_fetcher, "fetch_many", lambda *args, **kwargs: {})
    with app.app_context():
        cache.clear()

    first = client.get(
        "/api/v1/market-data/ema-summary?market=crypto", headers=summary_headers
    )
    assert first.status_code == 200
    assert [row["id"] for row in first.get_json()["assets"]] == [summary_assets["crypto"]]

    second = client.get(
        "/api/v1/market-data/ema-summary?market=forex", headers=summary_headers
    )
    assert second.status_code == 200
    assert [row["id"] for row in second.get_json()["assets"]] == [summary_assets["forex"]]
