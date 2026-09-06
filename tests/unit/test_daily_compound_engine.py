"""
Tests for app/services/daily_compound/engine.py — a port of the lost
Daily Compound Calculator Flutter app's CompoundInterestEngine, built
from its surviving documentation (see the engine module's own docstring).
Several tests below deliberately reproduce assertions the documentation
says existed in the original app's own test suite, so this port is
provably equivalent on the documented cases, not just plausible.
"""
from datetime import date

import pytest

from app.services.daily_compound.engine import (
    MAX_RESULT_MAGNITUDE,
    _add_months,
    _compounding_day_offsets,
    calculate,
)


class TestAddMonths:
    def test_clamps_to_shorter_month_end(self):
        # Jan 31 + 1 month = Feb 28 in a non-leap year — the documented example.
        assert _add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)

    def test_clamps_to_leap_february(self):
        assert _add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)

    def test_plain_addition_when_day_exists(self):
        assert _add_months(date(2026, 1, 15), 2) == date(2026, 3, 15)

    def test_rolls_over_year_boundary(self):
        assert _add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


class TestCompoundingDayOffsets:
    def test_daily_is_every_day(self):
        assert _compounding_day_offsets(date(2026, 1, 1), 5, "daily") == {1, 2, 3, 4, 5}

    def test_weekly_lands_exactly_on_multiple_of_seven(self):
        assert _compounding_day_offsets(date(2026, 1, 1), 14, "weekly") == {7, 14}

    def test_weekly_appends_final_partial_week(self):
        assert _compounding_day_offsets(date(2026, 1, 1), 10, "weekly") == {7, 10}

    def test_monthly_over_one_year_fires_twelve_times_landing_on_final_day(self):
        # Same setup as the "monthly compounding compounds 12 times over 1
        # year" case: 12 monthly compounding dates, the 12th landing
        # exactly on the requested end, so no extra final-day event.
        start = date(2026, 1, 1)
        total_days = (_add_months(start, 12) - start).days
        offsets = _compounding_day_offsets(start, total_days, "monthly")
        assert len(offsets) == 12
        assert max(offsets) == total_days

    def test_monthly_appends_final_day_when_period_ends_mid_month(self):
        start = date(2026, 1, 1)
        total_days = 40  # doesn't land exactly on a month boundary
        offsets = _compounding_day_offsets(start, total_days, "monthly")
        assert total_days in offsets


class TestCalculateCore:
    def test_monthly_one_percent_over_one_year_matches_documented_formula(self):
        # Directly reproduces the original app's own unit test assertion:
        # finalAmount == 10000 * 1.01^12 for monthly 1% over 1 year.
        result = calculate(
            principal=10000, rate_percent=1, start_date=date(2026, 1, 1),
            duration_value=1, duration_unit="years", frequency="monthly",
        )
        expected = 10000 * (1.01 ** 12)
        assert result.final_amount == pytest.approx(expected, rel=1e-9)
        assert not result.truncated

    def test_rate_is_applied_directly_not_annualized(self):
        # Daily 0.10% for 5 days: balance *= 1.0010 on every single day —
        # NOT the rate divided by 365. This is the core documented
        # design decision (02_TDD section 3.1).
        result = calculate(
            principal=1000, rate_percent=0.10, start_date=date(2026, 1, 1),
            duration_value=5, duration_unit="days", frequency="daily",
        )
        expected = 1000 * (1.001 ** 5)
        assert result.final_amount == pytest.approx(expected, rel=1e-9)

    def test_non_compounding_days_are_flat(self):
        # Monthly frequency over a short multi-day window before the first
        # compounding date: every day's schedule row should show zero
        # interest and opening == closing, but the schedule still has one
        # row per calendar day.
        result = calculate(
            principal=1000, rate_percent=5, start_date=date(2026, 1, 1),
            duration_value=10, duration_unit="days", frequency="monthly",
        )
        assert len(result.daily_schedule) == 10
        # Only the final day (the forced end-of-schedule event) should earn interest.
        non_zero_days = [d for d in result.daily_schedule if d.interest_earned > 0]
        assert len(non_zero_days) == 1
        assert non_zero_days[0].day == 10
        flat_days = [d for d in result.daily_schedule if d.interest_earned == 0]
        assert all(d.opening_balance == d.closing_balance for d in flat_days)

    def test_zero_or_negative_inputs_raise(self):
        kwargs = dict(start_date=date(2026, 1, 1), duration_value=1,
                      duration_unit="years", frequency="yearly")
        with pytest.raises(ValueError):
            calculate(principal=0, rate_percent=1, **kwargs)
        with pytest.raises(ValueError):
            calculate(principal=100, rate_percent=-1, **kwargs)
        with pytest.raises(ValueError):
            calculate(principal=100, rate_percent=1, start_date=date(2026, 1, 1),
                      duration_value=0, duration_unit="years", frequency="yearly")

    def test_invalid_duration_unit_and_frequency_raise(self):
        with pytest.raises(ValueError):
            calculate(principal=100, rate_percent=1, start_date=date(2026, 1, 1),
                      duration_value=1, duration_unit="fortnights", frequency="daily")
        with pytest.raises(ValueError):
            calculate(principal=100, rate_percent=1, start_date=date(2026, 1, 1),
                      duration_value=1, duration_unit="years", frequency="hourly")


class TestTruncation:
    def test_truncates_instead_of_growing_unbounded(self):
        # 20% daily compounded for a year — the documented example that
        # the original app's own test proved truncates rather than
        # throwing, with the schedule shorter than the full requested
        # duration and the final amount still past the cap.
        result = calculate(
            principal=10000, rate_percent=20, start_date=date(2026, 1, 1),
            duration_value=1, duration_unit="years", frequency="daily",
        )
        assert result.truncated is True
        assert len(result.daily_schedule) < 365
        # max_integer_digits defaults to 20 (its own documented ceiling),
        # so the *effective* cap is always 10**20, not the absolute
        # MAX_RESULT_MAGNITUDE (1e21) — 10**20 < 1e21 by construction, so
        # the user-configured cap is always what actually binds here.
        assert result.final_amount > 10 ** 20
        assert result.final_amount < MAX_RESULT_MAGNITUDE * 2  # sane upper bound, not runaway

    def test_lower_max_integer_digits_truncates_sooner(self):
        wide = calculate(
            principal=1000, rate_percent=20, start_date=date(2026, 1, 1),
            duration_value=1, duration_unit="years", frequency="daily",
            max_integer_digits=20,
        )
        narrow = calculate(
            principal=1000, rate_percent=20, start_date=date(2026, 1, 1),
            duration_value=1, duration_unit="years", frequency="daily",
            max_integer_digits=4,
        )
        assert narrow.truncated is True
        assert len(narrow.daily_schedule) <= len(wide.daily_schedule)

    def test_never_raises_for_any_valid_combination(self):
        # A broad sweep across frequencies/durations — the engine should
        # truncate, never throw, regardless of how aggressive the inputs are.
        for frequency in ("daily", "weekly", "monthly", "quarterly", "half_yearly", "yearly"):
            for rate in (0.01, 1, 50):
                result = calculate(
                    principal=100, rate_percent=rate, start_date=date(2026, 1, 1),
                    duration_value=2, duration_unit="years", frequency=frequency,
                )
                assert result.final_amount >= 0
                assert 0 <= len(result.daily_schedule)


class TestAggregation:
    def test_monthly_aggregation_reconciles_with_total_interest(self):
        result = calculate(
            principal=5000, rate_percent=2, start_date=date(2026, 1, 1),
            duration_value=1, duration_unit="years", frequency="monthly",
        )
        summed = sum(p.interest_earned for p in result.monthly_schedule)
        assert summed == pytest.approx(result.total_interest, rel=1e-9)

    def test_yearly_aggregation_reconciles_with_total_interest(self):
        result = calculate(
            principal=5000, rate_percent=2, start_date=date(2026, 1, 1),
            duration_value=3, duration_unit="years", frequency="yearly",
        )
        summed = sum(p.interest_earned for p in result.yearly_schedule)
        assert summed == pytest.approx(result.total_interest, rel=1e-9)

    def test_yearly_buckets_span_calendar_years_crossed(self):
        result = calculate(
            principal=1000, rate_percent=1, start_date=date(2026, 6, 1),
            duration_value=18, duration_unit="months", frequency="monthly",
        )
        years_seen = {p.period_start.year for p in result.yearly_schedule}
        assert years_seen == {2026, 2027}
