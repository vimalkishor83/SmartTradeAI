"""Authenticated HTTP coverage for Journal payloads and detail reads."""

import pytest


@pytest.fixture
def journal_client(app, client):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, User
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="free").first()
        user = User(
            username="journal-route-test",
            email="journal-route-test@example.com",
            role_id=role.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))

    return client, {"Authorization": f"Bearer {token}"}


def test_create_journal_entry_rejects_non_object_body(journal_client):
    client, headers = journal_client

    response = client.post("/api/v1/journal/", headers=headers, json=[])

    assert response.status_code == 400
    assert response.get_json()["error"] == "request body must be a JSON object"


def test_create_journal_entry_rejects_invalid_dates(journal_client):
    client, headers = journal_client

    response = client.post(
        "/api/v1/journal/", headers=headers, json={"trade_date": "not-a-date"}
    )

    assert response.status_code == 400
    assert "time data" in response.get_json()["error"]


def test_journal_detail_route_reads_entries_outside_first_page(journal_client):
    client, headers = journal_client
    created = client.post(
        "/api/v1/journal/",
        headers=headers,
        json={"trade_date": "2026-09-06", "entry_price": 100, "exit_price": 110},
    )
    entry_id = created.get_json()["id"]

    response = client.get(f"/api/v1/journal/{entry_id}", headers=headers)

    assert response.status_code == 200
    assert response.get_json()["id"] == entry_id
    assert response.get_json()["pnl_amount"] == 10.0


def test_update_journal_entry_rejects_non_object_body(journal_client):
    client, headers = journal_client
    created = client.post("/api/v1/journal/", headers=headers, json={})
    entry_id = created.get_json()["id"]

    response = client.put(f"/api/v1/journal/{entry_id}", headers=headers, json=[])

    assert response.status_code == 400
    assert response.get_json()["error"] == "request body must be a JSON object"
