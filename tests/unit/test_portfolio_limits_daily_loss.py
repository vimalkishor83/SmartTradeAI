"""Regression coverage for the daily-loss-limit timezone bug:
app/services/risk/portfolio_limits.py::evaluate_order_for_user() must find
"today's" JournalEntry rows using the same date convention those rows are
actually written with (a plain UTC calendar date -- see
frontend/templates/dashboard/journal.html's date-picker default,
`new Date().toISOString().slice(0,10)`), not a SCHEDULER_TIMEZONE-based
"business date". A prior change compared trade_date against an
Asia/Kolkata-based business date instead, which silently stopped matching
any journal entry once IST's calendar date diverged from UTC's -- i.e.
any time from 18:30 UTC to 23:59 UTC every single day, since
SCHEDULER_TIMEZONE defaults to "Asia/Kolkata" (UTC+5:30) in every config
profile (see app/config.py). This test pins that exact window down
deterministically instead of relying on whatever time of day the suite
happens to run at, which is how the bug went unnoticed by the one
end-to-end test that did cover it
(test_daily_loss_limit_rejects_order_before_broker_call in
test_safety_and_health_contracts.py) whenever CI happened to run before
18:30 UTC.
"""
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest


class _FakeDatetime(datetime):
    """Patches datetime.utcnow()/now() to a fixed instant while leaving
    every other datetime construction (date(), timedelta arithmetic, etc.)
    untouched -- swapping the whole `datetime` module out is overkill and
    breaks unrelated code that also imports it."""
    _fixed_utc = datetime(2026, 1, 1, 23, 0, 0, tzinfo=timezone.utc)  # 23:00 UTC = 04:30 IST *next* day

    @classmethod
    def utcnow(cls):
        return cls._fixed_utc.replace(tzinfo=None)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls._fixed_utc.replace(tzinfo=None)
        return cls._fixed_utc.astimezone(tz)


@pytest.fixture
def daily_loss_setup(app):
    from app.extensions import db
    from app.models.journal import JournalEntry
    from app.models.risk_limit import RiskLimit
    from app.models.user import Role, User

    with app.app_context():
        role = Role.query.filter_by(name="free").first()
        user = User(
            username="dailylosstz", email="dailylosstz@example.com",
            role_id=role.id, approval_status="approved",
        )
        user.set_password("TestPass123!")
        db.session.add(user)
        db.session.commit()

        db.session.add(RiskLimit(user_id=user.id, max_daily_loss=100, enabled=True))
        # Written with a plain UTC calendar date, matching how the real
        # journal date-picker and the pre-regression backend both derive
        # "today" -- date(2026, 1, 1), the UTC date at the fixed instant.
        db.session.add(JournalEntry(
            user_id=user.id, trade_date=date(2026, 1, 1), pnl_amount=-101,
        ))
        db.session.commit()
        return user.id


@pytest.mark.slow
def test_daily_loss_check_finds_todays_entry_when_ist_has_already_rolled_over(app, daily_loss_setup):
    """At 23:00 UTC, Asia/Kolkata (UTC+5:30) is already at 04:30 the next
    calendar day. Before the fix, business_date would be one day ahead of
    the UTC date the journal entry was actually stored under, the query
    would find nothing, and the daily-loss limit would silently not
    trigger -- exactly the fail-open bug this test locks in against."""
    from app.services.risk.portfolio_limits import evaluate_order_for_user

    with app.app_context():
        # datetime is imported locally inside evaluate_order_for_user
        # (`from datetime import datetime`), so there's no module-level
        # `portfolio_limits.datetime` attribute to patch -- patching the
        # real datetime.datetime class is what that local import actually
        # resolves against each time the function runs.
        with patch("datetime.datetime", _FakeDatetime):
            result = evaluate_order_for_user(
                daily_loss_setup, size=1, price=100,
            )

    assert result["allowed"] is False
    assert result["reason"] == "Portfolio daily loss limit exceeded"
    daily_loss_check = next(c for c in result["checks"] if c["name"] == "max_daily_loss")
    assert daily_loss_check["value"] == pytest.approx(101.0)
    assert daily_loss_check["passed"] is False
