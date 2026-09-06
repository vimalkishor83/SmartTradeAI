import pytest


@pytest.fixture
def dhan_headers(app):
    with app.app_context():
        from app.extensions import db
        from app.models.user import Role, User
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="free").first()
        user = User(
            username="dhanvalidation",
            email="dhanvalidation@example.com",
            role_id=role.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))

    return {"Authorization": f"Bearer {token}"}


def test_dhan_rejects_unknown_index_inputs(client, dhan_headers):
    response = client.get(
        "/api/v1/dhan/indices",
        headers=dhan_headers,
        query_string={"names": "NIFTY 50,UNKNOWN"},
    )
    assert response.status_code == 422
    assert "Unknown underlying" in response.get_json()["error"]

    response = client.get(
        "/api/v1/dhan/indices",
        headers=dhan_headers,
        query_string={"names": "EXTRA"},
    )
    assert response.status_code == 422
    assert "Unknown underlying" in response.get_json()["error"]


@pytest.mark.parametrize("path", [
    "/api/v1/dhan/options/expiries?underlying=UNKNOWN",
    "/api/v1/dhan/options/chain?underlying=UNKNOWN&expiry=2099-01-01",
])
def test_dhan_rejects_unknown_underlying_before_provider_access(client, dhan_headers, path):
    response = client.get(path, headers=dhan_headers)

    assert response.status_code == 422
    assert "Unknown underlying" in response.get_json()["error"]


@pytest.mark.parametrize("expiry", ["", "not-a-date", "2024-01-01", "2024-02-31", "2099-1-1"])
def test_dhan_rejects_invalid_or_expired_option_expiry(client, dhan_headers, expiry):
    response = client.get(
        "/api/v1/dhan/options/chain",
        headers=dhan_headers,
        query_string={"underlying": "NIFTY 50", "expiry": expiry},
    )

    assert response.status_code == 422
    assert "YYYY-MM-DD" in response.get_json()["error"]


def test_dhan_accepts_canonical_input_without_configuration(client, dhan_headers):
    response = client.get(
        "/api/v1/dhan/indices",
        headers=dhan_headers,
        query_string={"names": " nifty 50, NIFTY BANK "},
    )

    assert response.status_code == 200
    assert response.get_json() == {"configured": False, "quotes": {}}
