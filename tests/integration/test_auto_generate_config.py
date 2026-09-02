"""Integration test: proves two real production incidents are fixed —

1. POST /auto-generate/save silently stopped a running schedule. It only
   ever meant to persist settings (asset_ids/markets/timeframes/etc.),
   but it called _ag_save(), which persists EVERY _AG_PERSIST_KEYS field
   (including "running") from this process's local _AG_STATE. On the web
   tier that field is never the real running state — only the dedicated
   worker process executes a cycle and keeps it in sync — so it sits at
   its False default there, and a plain settings-only Save clobbered a
   genuinely running schedule's "running" flag back to False.

2. POST /auto-generate/stop had the same root cause for every OTHER
   config field: it explicitly set only "running" and "next_run_at" on
   the local state, then called _ag_save(), which re-persisted
   timeframes/interval_minutes/etc. from that same unreliable local
   copy — silently reverting real saved settings to whatever this
   process's local state happened to hold.

Both are reproduced here by seeding a DB config that intentionally
disagrees with the module's local _AG_STATE (simulating "this process's
local state is stale relative to the DB", exactly what happens on the
web tier), then calling the real HTTP routes and asserting the DB ends
up right.
"""
import pytest


@pytest.fixture
def super_admin_headers(app, client):
    with app.app_context():
        from app.extensions import db
        from app.models.user import User, Role
        from flask_jwt_extended import create_access_token

        role = Role.query.filter_by(name="admin").first()
        admin = User(username="agadmin", email="agadmin@example.com", role_id=role.id,
                     approval_status="approved", is_super_admin=True)
        admin.set_password("TestPass123!")
        db.session.add(admin)
        db.session.commit()
        token = create_access_token(identity=str(admin.id))
    return {"Authorization": f"Bearer {token}"}


def _seed_running_config(app, **overrides):
    with app.app_context():
        from app.extensions import db
        from app.models.auto_generate_config import AutoGenerateConfig
        row = AutoGenerateConfig.query.first()
        if row is None:
            row = AutoGenerateConfig()
            db.session.add(row)
        row.running = True
        row.timeframes = ["5m", "15m"]
        row.interval_minutes = 20
        row.markets = ["crypto"]
        for k, v in overrides.items():
            setattr(row, k, v)
        db.session.commit()


class TestAutoGenerateSaveDoesNotStopSchedule:
    def test_save_config_preserves_running_true(self, app, client, super_admin_headers):
        _seed_running_config(app)

        # Simulate the web tier's local _AG_STATE being stale/default —
        # exactly the real-world condition (this process never ran a
        # cycle, so its "running" sits at the module's False default).
        with app.app_context():
            from app.api.v1.signals import _AG_STATE
            assert _AG_STATE["running"] is False

        resp = client.post(
            "/api/v1/signals/auto-generate/save",
            json={"timeframes": ["5m", "15m", "1h"], "interval_minutes": 30},
            headers=super_admin_headers,
        )
        assert resp.status_code == 200

        with app.app_context():
            from app.models.auto_generate_config import AutoGenerateConfig
            row = AutoGenerateConfig.query.first()
            # The actual regression: this used to come back False.
            assert row.running is True
            assert row.timeframes == ["5m", "15m", "1h"]


class TestAutoGenerateStopDoesNotRevertOtherSettings:
    def test_stop_only_changes_running(self, app, client, super_admin_headers):
        _seed_running_config(app)

        with app.app_context():
            from app.api.v1.signals import _AG_STATE
            # Force this process's local state to disagree with the DB —
            # _AG_STATE is a module-level global that outlives any single
            # request/test, so pin it explicitly rather than relying on
            # whatever a previous test happened to leave behind. This is
            # exactly the real-world condition that let ag_stop() silently
            # re-persist the wrong values: the web tier's local copy is
            # stale relative to the DB the worker/other replicas wrote.
            _AG_STATE["timeframes"] = ["1h"]
            _AG_STATE["interval_minutes"] = 5
            _AG_STATE["markets"] = []

        resp = client.post("/api/v1/signals/auto-generate/stop", headers=super_admin_headers)
        assert resp.status_code == 200

        with app.app_context():
            from app.models.auto_generate_config import AutoGenerateConfig
            row = AutoGenerateConfig.query.first()
            assert row.running is False
            # The actual regression: these used to get reverted to
            # _AG_STATE's stale local values (["1h"], 5).
            assert row.timeframes == ["5m", "15m"]
            assert row.interval_minutes == 20
            assert row.markets == ["crypto"]
