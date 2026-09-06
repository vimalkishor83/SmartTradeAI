"""Integration coverage for authenticated admin asset mutations."""

import pytest


@pytest.fixture
def super_admin_headers(app, client):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, User
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="admin").first()
        user = User(username="assetadmin", email="assetadmin@example.com", role_id=role.id,
                    approval_status="approved", is_super_admin=True)
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))

    return {"Authorization": f"Bearer {token}"}


class TestAssetMutations:
    def test_non_object_bodies_return_400(self, client, super_admin_headers):
        for method, path in (("post", "/api/v1/assets/"), ("put", "/api/v1/assets/1"),
                             ("post", "/api/v1/assets/add-from-search")):
            response = getattr(client, method)(path, headers=super_admin_headers, json=[])
            assert response.status_code == 400
            assert response.get_json()["error"] == "request body must be a JSON object"

    @pytest.mark.parametrize("payload", [
        {"symbol": "BTC", "name": "Bitcoin", "market": "unknown"},
        {"symbol": "<script>", "name": "Unsafe", "market": "crypto"},
        {"symbol": "BTC", "name": "Bitcoin", "market": "crypto", "is_active": "false"},
        {"symbol": "BTC", "name": "Bitcoin", "market": "crypto", "pip_size": "nan"},
        {"symbol": "BTC", "name": "x" * 101, "market": "crypto"},
    ])
    def test_create_rejects_invalid_values(self, client, super_admin_headers, payload):
        response = client.post("/api/v1/assets/", headers=super_admin_headers, json=payload)

        assert response.status_code == 400

    def test_create_normalizes_symbol_and_update_requires_editable_field(self, client, super_admin_headers):
        response = client.post("/api/v1/assets/", headers=super_admin_headers, json={
            "symbol": " testusd ", "name": "Test USD", "market": "forex",
            "exchange": "Yahoo", "is_active": True,
        })

        assert response.status_code == 201
        asset_id = response.get_json()["id"]
        assert response.get_json()["symbol"] == "TESTUSD"

        empty_update = client.put(f"/api/v1/assets/{asset_id}", headers=super_admin_headers, json={})
        assert empty_update.status_code == 400

        update = client.put(f"/api/v1/assets/{asset_id}", headers=super_admin_headers, json={
            "is_active": False,
        })
        assert update.status_code == 200
        assert update.get_json()["is_active"] is False

    def test_add_from_search_rejects_unknown_source_and_market(self, client, super_admin_headers):
        for payload in (
            {"symbol": "TEST", "name": "Test", "source": "unknown"},
            {"symbol": "TEST", "name": "Test", "market": "unknown"},
        ):
            response = client.post("/api/v1/assets/add-from-search", headers=super_admin_headers, json=payload)
            assert response.status_code == 400
