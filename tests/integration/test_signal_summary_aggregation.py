"""Regression coverage for the signal-summary aggregate query contract."""

from datetime import datetime

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
            username="summaryaggregate",
            email="summaryaggregate@example.com",
            role_id=role.id,
            subscription_id=subscription.id,
            approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}


def test_summary_uses_two_history_aggregates_and_preserves_metrics(
    app, client, login_headers,
):
    with app.app_context():
        from app.extensions import cache, db
        from app.models.signal import SignalHistory

        cache.delete("signals_summary")
        db.session.add_all([
            SignalHistory(outcome="win", pnl_pct=2.0, closed_at=datetime.utcnow()),
            SignalHistory(outcome="loss", pnl_pct=-1.0, closed_at=datetime.utcnow()),
            SignalHistory(outcome="neutral", pnl_pct=0.0, closed_at=datetime.utcnow()),
        ])
        db.session.commit()

    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "signal_history" in statement.lower():
            statements.append(statement)

    from sqlalchemy import event
    from app.extensions import db

    with app.app_context():
        engine = db.engine
        event.listen(engine, "before_cursor_execute", capture)
        try:
            response = client.get("/api/v1/signals/summary", headers=login_headers)
        finally:
            event.remove(engine, "before_cursor_execute", capture)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total_historical"] == 3
    assert payload["win_rate"] == 33.3
    assert payload["closed_today"] == 3
    assert payload["wins_today"] == 1
    assert payload["losses_today"] == 1
    assert payload["total_pnl_today"] == 1.0
    assert len(statements) == 2
