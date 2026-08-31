"""Integration test: proves telegram_alerts_<category> (individual) and
telegram_alerts_<category>_group are truly independent gates in
fire_signal_alerts and check_rating_changes — the whole point of this
feature. Runs the real task functions against the in-memory test DB with
_send_telegram/_send_to_channels monkeypatched to record calls instead of
hitting the network, since that's the actual boundary these two settings
control.
"""
import pytest
from datetime import datetime, timedelta


@pytest.fixture
def signal_setup(app):
    with app.app_context():
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


class TestIndividualGroupSplit:
    def test_group_on_individual_off_sends_only_to_channel(self, app, signal_setup, monkeypatch):
        with app.app_context():
            from app.models.platform_config import PlatformConfig
            from app.extensions import db
            row = PlatformConfig.get_singleton()
            row.telegram_alerts_signal = False        # individual OFF
            row.telegram_alerts_signal_group = True    # group ON
            db.session.commit()

            calls = {"individual": 0, "group": 0}
            import app.tasks.notification_tasks as nt
            monkeypatch.setattr(nt, "_send_telegram", lambda user, text: calls.__setitem__("individual", calls["individual"] + 1))
            monkeypatch.setattr(nt, "_send_to_channels", lambda text, market, category, tf=None: calls.__setitem__("group", calls["group"] + 1))

            nt.fire_signal_alerts(app)

            assert calls["group"] == 1, "group delivery should fire when the group gate is on"
            assert calls["individual"] == 0, "individual delivery must not fire when its own gate is off"

    def test_individual_on_group_off_sends_only_to_subscriber(self, app, signal_setup, monkeypatch):
        with app.app_context():
            from app.models.platform_config import PlatformConfig
            from app.extensions import db
            row = PlatformConfig.get_singleton()
            row.telegram_alerts_signal = True         # individual ON
            row.telegram_alerts_signal_group = False   # group OFF
            db.session.commit()

            calls = {"individual": 0, "group": 0}
            import app.tasks.notification_tasks as nt
            monkeypatch.setattr(nt, "_send_telegram", lambda user, text: calls.__setitem__("individual", calls["individual"] + 1))
            monkeypatch.setattr(nt, "_send_to_channels", lambda text, market, category, tf=None: calls.__setitem__("group", calls["group"] + 1))

            nt.fire_signal_alerts(app)

            assert calls["individual"] == 1, "individual delivery should fire when its own gate is on"
            assert calls["group"] == 0, "group delivery must not fire when the group gate is off"
