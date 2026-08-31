"""Integration test: real Flask app + in-memory SQLite DB + real JWT auth,
hitting the actual HTTP routes for the new TelegramAlertChannel CRUD —
proves the routes, decorators, and (de)serialization work together, not
just the model/formatter logic in isolation.
"""
import pytest


@pytest.fixture
def super_admin_client(app, client):
    with app.app_context():
        from app.extensions import db
        from app.models.user import User, Role

        role = Role.query.filter_by(name="admin").first()
        user = User(username="superadmin", email="superadmin@example.com", role_id=role.id,
                    approval_status="approved", is_super_admin=True)
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()

        from flask_jwt_extended import create_access_token
        token = create_access_token(identity=str(user.id))

    return client, {"Authorization": f"Bearer {token}"}


class TestTelegramChannelsCrud:
    def test_create_list_update_delete_channel(self, super_admin_client):
        client, headers = super_admin_client

        # Create
        resp = client.post("/api/v1/admin/telegram/channels", headers=headers, json={
            "name": "Crypto Signals", "group_chat_id": "-100111", "markets": ["crypto"],
            "alerts_signal": True, "alerts_rating_change": True,
        })
        assert resp.status_code == 201
        body = resp.get_json()
        channel_id = body["id"]
        assert body["name"] == "Crypto Signals"
        assert body["markets"] == ["crypto"]
        assert body["alerts_signal"] is True
        assert body["alerts_signal_closed"] is True  # model default
        assert "alerts_watchlist" not in body  # removed — group-level never sends these

        # List
        resp = client.get("/api/v1/admin/telegram/channels", headers=headers)
        assert resp.status_code == 200
        assert len(resp.get_json()["channels"]) == 1

        # Update
        resp = client.put(f"/api/v1/admin/telegram/channels/{channel_id}", headers=headers, json={
            "markets": ["crypto", "forex"], "is_active": False,
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["markets"] == ["crypto", "forex"]
        assert body["is_active"] is False

        # Delete
        resp = client.delete(f"/api/v1/admin/telegram/channels/{channel_id}", headers=headers)
        assert resp.status_code == 200
        resp = client.get("/api/v1/admin/telegram/channels", headers=headers)
        assert resp.get_json()["channels"] == []

    def test_create_missing_name_returns_400(self, super_admin_client):
        client, headers = super_admin_client
        resp = client.post("/api/v1/admin/telegram/channels", headers=headers, json={
            "group_chat_id": "-100111",
        })
        assert resp.status_code == 400

    def test_create_invalid_market_returns_400(self, super_admin_client):
        client, headers = super_admin_client
        resp = client.post("/api/v1/admin/telegram/channels", headers=headers, json={
            "name": "Bad", "group_chat_id": "-100111", "markets": ["not_a_real_market"],
        })
        assert resp.status_code == 400

    def test_regular_admin_cannot_create_channel(self, app, client):
        """admin_required allows listing, but mutations need super_admin_required."""
        with app.app_context():
            from app.extensions import db
            from app.models.user import User, Role

            role = Role.query.filter_by(name="admin").first()
            user = User(username="plainadmin", email="plainadmin@example.com", role_id=role.id,
                        approval_status="approved", is_super_admin=False)
            user.set_password("TestPass123!")
            db.session.add(user)
            db.session.commit()

            from flask_jwt_extended import create_access_token
            token = create_access_token(identity=str(user.id))

        headers = {"Authorization": f"Bearer {token}"}
        resp = client.post("/api/v1/admin/telegram/channels", headers=headers, json={
            "name": "X", "group_chat_id": "-1",
        })
        assert resp.status_code == 403

        resp = client.get("/api/v1/admin/telegram/channels", headers=headers)
        assert resp.status_code == 200
