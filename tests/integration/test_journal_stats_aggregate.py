"""Regression coverage for SQL-backed journal statistics."""

from datetime import date

import pytest


@pytest.fixture
def login_headers(app):
    with app.app_context():
        from app.models.user import User
        from flask_jwt_extended import create_access_token

        user = User.query.filter_by(username="admin").first()
        token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}


def test_journal_stats_preserves_financial_breakdown_contract(
    app, client, login_headers,
):
    with app.app_context():
        from app.extensions import db
        from app.models.journal import JournalEntry
        from app.models.user import User

        user_id = User.query.filter_by(username="admin").first().id
        db.session.add_all([
            JournalEntry(
                user_id=user_id, trade_date=date(2026, 9, 7), market="crypto",
                outcome="win", pnl_amount=100.0, emotion_tag="disciplined",
            ),
            JournalEntry(
                user_id=user_id, trade_date=date(2026, 9, 8), market="crypto",
                outcome="loss", pnl_amount=-40.0, emotion_tag="anxious",
            ),
            JournalEntry(
                user_id=user_id, trade_date=date(2026, 9, 9), market="forex",
                outcome="breakeven", pnl_amount=0.0, emotion_tag="fomo",
            ),
            JournalEntry(
                user_id=user_id, trade_date=date(2026, 9, 9), market=None,
                outcome=None, pnl_amount=None, emotion_tag="",
            ),
        ])
        db.session.commit()

    response = client.get("/api/v1/journal/stats", headers=login_headers)

    assert response.status_code == 200
    assert response.get_json() == {
        "total_trades": 4,
        "win_rate": 25.0,
        "total_pnl": 60.0,
        "avg_pnl_per_trade": 15.0,
        "best_trade": 100.0,
        "worst_trade": -40.0,
        "avg_win": 100.0,
        "avg_loss": -40.0,
        "profit_factor": 2.5,
        "by_emotion": {
            "anxious": {"trades": 1, "win_rate": 0.0},
            "disciplined": {"trades": 1, "win_rate": 100.0},
            "fomo": {"trades": 1, "win_rate": 0.0},
            "unknown": {"trades": 1, "win_rate": 0.0},
        },
        "by_market": {
            "crypto": {"trades": 2, "win_rate": 50.0, "pnl": 60.0},
            "forex": {"trades": 1, "win_rate": 0.0, "pnl": 0.0},
            "unknown": {"trades": 1, "win_rate": 0.0, "pnl": 0.0},
        },
        "by_day_of_week": {
            "Monday": {"trades": 1, "win_rate": 100.0},
            "Tuesday": {"trades": 1, "win_rate": 0.0},
            "Wednesday": {"trades": 2, "win_rate": 0.0},
        },
    }
