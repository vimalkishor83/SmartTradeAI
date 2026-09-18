"""Integration tests for individual signal and news-group routing."""

import pytest
from datetime import datetime


@pytest.fixture
def signal_setup(app):
    with app.app_context():
        app.config["TELEGRAM_NOTIFICATIONS_ENABLED"] = True
        app.config["TELEGRAM_DELIVERY_MODE"] = "news_group_individual_signals"

        from app.extensions import db
        from app.models.user import User, Role
        from app.models.asset import Asset
        from app.models.signal import Signal

        role = Role.query.filter_by(name="free").first()
        user = User(username="tgsplituser", email="tgsplit@example.com", role_id=role.id,
                    approval_status="approved", is_active=True,
                    telegram_enabled=True, telegram_chat_id="12345")
        user.set_password("TestPass123!")
        db.session.add(user)

        asset = Asset(symbol="BTCUSDT", name="Bitcoin", market="crypto", is_active=True)
        db.session.add(asset)
        db.session.commit()

        sig = Signal(
            asset_id=asset.id, signal_type="BUY", timeframe="1h",
            entry_price=100.0, stop_loss=95.0, target1=105.0, target2=110.0, target3=115.0,
            confidence_score=90.0, confidence_label="Strong", risk_reward=1.5,
            status="active", generated_at=datetime.utcnow(),
        )
        db.session.add(sig)
        db.session.commit()
        return {"user_id": user.id, "asset_id": asset.id}


class TestNewsGroupIndividualSignalDelivery:
    def test_signal_group_settings_never_send_to_news_group(self, app, signal_setup, monkeypatch):
        with app.app_context():
            from app.models.platform_config import PlatformConfig
            from app.extensions import db
            row = PlatformConfig.get_singleton()
            row.telegram_signal_individual_markets = []
            row.telegram_signal_group_markets = ["crypto"]
            db.session.commit()

            calls = {"individual": 0, "group": 0}
            import app.tasks.notification_tasks as nt
            monkeypatch.setattr(
                nt, "_send_telegram",
                lambda user, text: calls.__setitem__("individual", calls["individual"] + 1),
            )
            monkeypatch.setattr(
                nt, "_send_to_channels",
                lambda text, market, category, tf=None: calls.__setitem__("group", calls["group"] + 1),
            )

            nt.fire_signal_alerts(app)

            assert calls["group"] == 0, "signal alerts must never use the news group"
            assert calls["individual"] == 0, "individual delivery is disabled for this market"

    def test_individual_signal_settings_send_only_to_users(self, app, signal_setup, monkeypatch):
        with app.app_context():
            from app.models.platform_config import PlatformConfig
            from app.extensions import db
            row = PlatformConfig.get_singleton()
            row.telegram_signal_individual_markets = ["crypto"]
            row.telegram_signal_group_markets = ["crypto"]
            db.session.commit()

            calls = {"individual": 0, "group": 0}
            import app.tasks.notification_tasks as nt
            monkeypatch.setattr(
                nt, "_send_telegram",
                lambda user, text: calls.__setitem__("individual", calls["individual"] + 1),
            )
            monkeypatch.setattr(
                nt, "_send_to_channels",
                lambda text, market, category, tf=None: calls.__setitem__("group", calls["group"] + 1),
            )

            nt.fire_signal_alerts(app)

            assert calls["individual"] == 1, "individual signal delivery should fire for an enabled market"
            assert calls["group"] == 0, "signal alerts must never use the news group"

    def test_market_not_in_individual_list_sends_nothing(self, app, signal_setup, monkeypatch):
        with app.app_context():
            from app.models.platform_config import PlatformConfig
            from app.extensions import db
            row = PlatformConfig.get_singleton()
            row.telegram_signal_individual_markets = ["forex"]
            row.telegram_signal_group_markets = ["crypto"]
            db.session.commit()

            calls = {"individual": 0, "group": 0}
            import app.tasks.notification_tasks as nt
            monkeypatch.setattr(
                nt, "_send_telegram",
                lambda user, text: calls.__setitem__("individual", calls["individual"] + 1),
            )
            monkeypatch.setattr(
                nt, "_send_to_channels",
                lambda text, market, category, tf=None: calls.__setitem__("group", calls["group"] + 1),
            )

            nt.fire_signal_alerts(app)

            assert calls == {"individual": 0, "group": 0}
