"""Terminal live-read performance keeps open and expired reads separate."""

from datetime import datetime, timedelta


def test_terminal_performance_separates_open_and_expired(app):
    with app.app_context():
        from app.extensions import db
        from app.models.asset import Asset
        from app.models.live_read_log import LiveReadLog
        from app.services.signals.live_read_performance import build_live_read_performance

        asset = Asset(symbol="PERFTERM", name="Terminal Performance", market="crypto", is_active=True)
        db.session.add(asset)
        db.session.flush()
        now = datetime.utcnow()
        common = dict(
            asset_id=asset.id, timeframe="15m", signal_type="BUY",
            confidence_score=70, entry_price=100, stop_loss=95,
            target1=105, target2=110, target3=115, snapshot={}, event_history=[],
        )
        db.session.add_all([
            LiveReadLog(**common, outcome="win", exit_price=115,
                        generated_at=now - timedelta(hours=2), resolved_at=now - timedelta(hours=1)),
            LiveReadLog(**common, outcome="loss", exit_price=95,
                        generated_at=now - timedelta(hours=2), resolved_at=now - timedelta(minutes=50)),
            LiveReadLog(**common, outcome="expired", exit_price=None,
                        generated_at=now - timedelta(hours=2), resolved_at=now - timedelta(minutes=40)),
            LiveReadLog(**common, outcome=None, current_price=104, trail_stage=1,
                        generated_at=now - timedelta(minutes=30), last_observed_at=now),
        ])
        db.session.commit()

        payload = build_live_read_performance()

    assert payload["total_logged"] == 4
    assert payload["resolved"] == 3
    assert payload["open"] == 1
    assert payload["expired"] == 1
    assert payload["decisive"] == 2
    assert payload["win_rate"] == 50.0
    assert payload["closed"]["net_pnl_pct"] == 10.0
    assert payload["open_stats"]["count"] == 1
    assert payload["open_stats"]["avg_unrealized_pnl_pct"] == 4.0
    assert payload["open_stats"]["by_stage"] == [{"stage": 1, "label": "After T1", "count": 1}]

    timeframe = payload["by_timeframe"][0]
    assert timeframe["total"] == 4
    assert timeframe["open"] == 1
    assert timeframe["decisive"] == 2
    assert timeframe["expired"] == 1
    assert timeframe["win_rate"] == 50.0


def test_terminal_performance_date_range_keeps_current_open_snapshot(app):
    with app.app_context():
        from app.extensions import db
        from app.models.asset import Asset
        from app.models.live_read_log import LiveReadLog
        from app.services.signals.live_read_performance import build_live_read_performance

        asset = Asset(symbol="RANGE_TERM", name="Range Terminal", market="crypto", is_active=True)
        db.session.add(asset)
        db.session.flush()
        db.session.add(LiveReadLog(
            asset_id=asset.id, timeframe="1h", signal_type="SELL",
            entry_price=100, stop_loss=105, target1=95, target2=90, target3=85,
            outcome="win", exit_price=85,
            generated_at=datetime(2026, 8, 1), resolved_at=datetime(2026, 8, 2),
            snapshot={}, event_history=[],
        ))
        db.session.add(LiveReadLog(
            asset_id=asset.id, timeframe="1h", signal_type="SELL",
            entry_price=100, stop_loss=105, target1=95, target2=90, target3=85,
            current_price=98, outcome=None,
            generated_at=datetime(2026, 1, 1), snapshot={}, event_history=[],
        ))
        db.session.commit()

        payload = build_live_read_performance(
            start_at=datetime(2026, 9, 1), end_at=datetime(2026, 9, 11),
        )

    assert payload["closed"]["total"] == 0
    assert payload["closed"]["decisive"] == 0
    assert payload["win_rate"] is None
    assert payload["open"] == 1
    assert payload["open_stats"]["avg_unrealized_pnl_pct"] == 2.0
