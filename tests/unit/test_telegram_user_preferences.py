"""Per-user Telegram alert preference: narrows personal delivery on top
of (never wider than) PlatformConfig's existing category/market gates."""

from types import SimpleNamespace
from unittest.mock import Mock

from app.services.notifications.telegram_user_preferences import (
    user_wants_telegram_category,
    invalidate_user_telegram_preference,
)


def _make_user(app, username="tguser"):
    from app.extensions import db
    from app.models.user import Role, User

    role = Role.query.filter_by(name="free").first()
    user = User(
        username=username, email=f"{username}@example.com",
        role_id=role.id, approval_status="approved",
        telegram_enabled=True, telegram_chat_id="555",
    )
    user.set_password("TestPass123!")
    db.session.add(user)
    db.session.commit()
    return user


def test_user_with_no_preference_row_allows_every_category(app):
    with app.app_context():
        user = _make_user(app)
        assert user_wants_telegram_category(user.id, "signal") is True
        assert user_wants_telegram_category(user.id, "watchlist") is True


def test_user_preference_narrows_to_selected_categories(app):
    from app.extensions import db
    from app.models.telegram_user_preference import TelegramUserPreference

    with app.app_context():
        user = _make_user(app, "tguser2")
        db.session.add(TelegramUserPreference(user_id=user.id, categories=["signal"]))
        db.session.commit()
        invalidate_user_telegram_preference(user.id)

        assert user_wants_telegram_category(user.id, "signal") is True
        assert user_wants_telegram_category(user.id, "watchlist") is False
        assert user_wants_telegram_category(user.id, "rating_change") is False


def test_user_preference_narrows_by_market(app):
    from app.extensions import db
    from app.models.telegram_user_preference import TelegramUserPreference

    with app.app_context():
        user = _make_user(app, "tguser3")
        db.session.add(TelegramUserPreference(user_id=user.id, markets=["crypto"]))
        db.session.commit()
        invalidate_user_telegram_preference(user.id)

        assert user_wants_telegram_category(user.id, "signal", market="crypto") is True
        assert user_wants_telegram_category(user.id, "signal", market="forex") is False
        # No market given at all -- the check is skipped, not failed.
        assert user_wants_telegram_category(user.id, "signal") is True


def test_send_telegram_respects_user_category_preference(app, monkeypatch):
    from app.extensions import db
    from app.models.telegram_user_preference import TelegramUserPreference

    with app.app_context():
        app.config["TELEGRAM_NOTIFICATIONS_ENABLED"] = True
        app.config["TELEGRAM_DELIVERY_MODE"] = "news_group_individual_signals"
        app.config["TELEGRAM_BOT_TOKEN"] = "platform-token"

        user = _make_user(app, "tguser4")
        db.session.add(TelegramUserPreference(user_id=user.id, categories=["signal"]))
        db.session.commit()
        invalidate_user_telegram_preference(user.id)
        db.session.refresh(user)

        requests_post = Mock(return_value=SimpleNamespace(ok=True, status_code=200))
        monkeypatch.setattr("requests.post", requests_post)

        from app.tasks.notification_tasks import _send_telegram

        assert _send_telegram(user, "watchlist message", category="watchlist") is False
        requests_post.assert_not_called()

        assert _send_telegram(user, "signal message", category="signal") is True
        requests_post.assert_called_once()


def test_send_telegram_without_category_skips_user_preference_check(app, monkeypatch):
    """The generic pending-notification sweep's legacy call (no category)
    must keep working exactly as before this feature -- untouched by any
    per-user restriction."""
    from app.extensions import db
    from app.models.telegram_user_preference import TelegramUserPreference

    with app.app_context():
        app.config["TELEGRAM_NOTIFICATIONS_ENABLED"] = True
        app.config["TELEGRAM_DELIVERY_MODE"] = "news_group_individual_signals"
        app.config["TELEGRAM_BOT_TOKEN"] = "platform-token"

        user = _make_user(app, "tguser5")
        db.session.add(TelegramUserPreference(user_id=user.id, categories=["signal"]))
        db.session.commit()
        invalidate_user_telegram_preference(user.id)
        db.session.refresh(user)

        requests_post = Mock(return_value=SimpleNamespace(ok=True, status_code=200))
        monkeypatch.setattr("requests.post", requests_post)

        from app.tasks.notification_tasks import _send_telegram

        assert _send_telegram(user, "generic message") is True
        requests_post.assert_called_once()
