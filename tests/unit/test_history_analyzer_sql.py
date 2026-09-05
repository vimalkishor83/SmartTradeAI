"""Regression coverage for SQL-backed history analytics."""

from datetime import datetime

from app.extensions import db
from app.models.asset import Asset
from app.models.signal import SignalHistory


def test_history_analytics_preserves_aggregate_contract(app, client):
    from app.services.backtest import analyze_history, whatif_expiry
    from app.models.user import User
    from flask_jwt_extended import create_access_token

    with app.app_context():
        asset = Asset(
            symbol="HISTSQL",
            name="History SQL Asset",
            market="crypto",
            is_active=True,
        )
        db.session.add(asset)
        db.session.flush()
        now = datetime.utcnow()
        db.session.add_all([
            SignalHistory(
                asset_id=asset.id,
                timeframe="1h",
                signal_type="BUY",
                confidence_score=75,
                outcome="win",
                pnl_pct=10.0,
                closed_at=now,
            ),
            SignalHistory(
                asset_id=asset.id,
                timeframe="1h",
                signal_type="SELL",
                confidence_score=65,
                outcome="loss",
                pnl_pct=-5.0,
                closed_at=now,
            ),
            SignalHistory(
                asset_id=asset.id,
                timeframe="4h",
                signal_type="BUY",
                confidence_score=55,
                outcome="neutral",
                pnl_pct=2.0,
                closed_at=now,
            ),
            SignalHistory(
                asset_id=asset.id,
                timeframe="4h",
                signal_type="HOLD",
                confidence_score=None,
                outcome=None,
                pnl_pct=None,
                closed_at=now,
            ),
        ])
        db.session.commit()

        stats = analyze_history()
        expiry = whatif_expiry()

        assert stats["overall"] == {
            "total": 4,
            "wins": 1,
            "losses": 1,
            "neutral": 2,
            "raw_win_rate": 25.0,
            "true_win_rate": 50.0,
            "avg_pnl_pct": 2.33,
            "profit_factor": 2.0,
        }
        assert stats["by_market"] == [{
            "market": "crypto",
            **stats["overall"],
        }]
        assert [(row["timeframe"], row["total"]) for row in stats["by_timeframe"]] == [
            ("1h", 2),
            ("4h", 2),
        ]
        assert [(row["signal_type"], row["total"]) for row in stats["by_signal_type"]] == [
            ("BUY", 2),
            ("HOLD", 1),
            ("SELL", 1),
        ]
        assert {row["range"]: row["total"] for row in stats["by_confidence"]} == {
            "50-60%": 1,
            "60-70%": 1,
            "70-80%": 1,
            "80-90%": 0,
            "90-100%": 0,
        }
        assert expiry["neutral_signals"] == 2
        assert expiry["moving_right_direction"] == 1
        assert expiry["moving_wrong_direction"] == 0
        assert expiry["flat"] == 1
        assert expiry["pct_neutral_in_profit"] == 50.0
        assert expiry["current_raw_win_rate"] == 25.0
        assert expiry["win_rate_if_neutral_profit_counted"] == 50.0
        assert expiry["interpretation"].startswith("If a high share of neutral signals")

        token = create_access_token(identity=str(User.query.filter_by(username="admin").first().id))

    response = client.get(
        "/api/v1/signals/history-stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.get_json()["stats"]["overall"]["total"] == 4
