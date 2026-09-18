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

    # The app's own _seed_initial_data() seeds several real crypto/forex
    # assets on every fresh test database (BTCUSDT, ETHUSDT, EURUSD, ...),
    # so a market=crypto response legitimately contains more than just
    # this fixture's one asset -- asserting an exact single-item list was
    # never a valid test of the actual behavior. What's worth proving here
    # is the thing the test name says: a cold-cache build still populates
    # the FULL active universe (not narrowed to whichever market the first
    # request happened to ask for), so per-request market filtering keeps
    # working correctly on the very next call. That means: this fixture's
    # own asset shows up under its own market, and never leaks into the
    # other market's response.
    first = client.get(
        "/api/v1/market-data/ta-summary?market=crypto", headers=summary_headers
    )
    assert first.status_code == 200
    first_ids = [row["id"] for row in first.get_json()["assets"]]
    assert summary_assets["crypto"] in first_ids
    assert summary_assets["forex"] not in first_ids
    assert all(row["market"] == "crypto" for row in first.get_json()["assets"])

    second = client.get(
        "/api/v1/market-data/ta-summary?market=forex", headers=summary_headers
    )
    assert second.status_code == 200
    second_ids = [row["id"] for row in second.get_json()["assets"]]
    assert summary_assets["forex"] in second_ids
    assert summary_assets["crypto"] not in second_ids
    assert all(row["market"] == "forex" for row in second.get_json()["assets"])


def test_ema_summary_cold_cache_keeps_the_full_active_universe(
    app, client, monkeypatch, summary_headers, summary_assets
):
    from app.api.v1 import market_data
    from app.extensions import cache

    monkeypatch.setattr(market_data, "blocked_data_markets", lambda: set())
    monkeypatch.setattr(market_data.market_fetcher, "fetch_many", lambda *args, **kwargs: {})
    with app.app_context():
        cache.clear()

    # Same reasoning as test_ta_summary_cold_cache_keeps_the_full_active_universe
    # above -- the seeded default assets mean an exact single-item list was
    # never a valid assertion; what matters is correct per-market scoping.
    first = client.get(
        "/api/v1/market-data/ema-summary?market=crypto", headers=summary_headers
    )
    assert first.status_code == 200
    first_ids = [row["id"] for row in first.get_json()["assets"]]
    assert summary_assets["crypto"] in first_ids
    assert summary_assets["forex"] not in first_ids
    assert all(row["market"] == "crypto" for row in first.get_json()["assets"])

    second = client.get(
        "/api/v1/market-data/ema-summary?market=forex", headers=summary_headers
    )
    assert second.status_code == 200
    second_ids = [row["id"] for row in second.get_json()["assets"]]
    assert summary_assets["forex"] in second_ids
    assert summary_assets["crypto"] not in second_ids
    assert all(row["market"] == "forex" for row in second.get_json()["assets"])
