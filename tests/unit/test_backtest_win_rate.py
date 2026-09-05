"""
Regression tests for the walk-forward backtest's win-rate/summary math
(app/services/backtest/runner.py::_summarize).

Written after a real production bug: the Backtesting page's "Live Engine"
mode displayed win rates like "4740%". The bug itself was a *frontend*
double-multiplication (backtesting.html multiplied an already-0-100-scale
win_rate by 100 again) — _summarize()'s own math was already correct —
but there was zero test coverage locking in the contract that win_rate/
raw_win_rate are always 0-100-scale percentages, bounded, and sane on
every edge case (zero trades, all wins, all losses, no losses for
profit_factor, etc). These tests exist so any future change to this
function that breaks that contract fails CI instead of reaching users.
"""
import math

from app.services.backtest.runner import _summarize


def _trade(outcome, r=None, pnl_pct=None):
    return {"outcome": outcome, "r": r, "pnl_pct": pnl_pct}


class TestWinRateBounds:
    def test_zero_trades_returns_zero_not_error_or_nan(self):
        summary = _summarize([])
        assert summary["trades"] == 0
        assert summary["wins"] == 0
        assert summary["losses"] == 0
        assert summary["expired"] == 0
        assert summary["win_rate"] == 0.0
        assert summary["raw_win_rate"] == 0.0
        assert summary["avg_r"] == 0.0
        assert summary["profit_factor"] == 0.0
        # Explicitly guard against the failure modes a naive division would
        # produce for an empty list (ZeroDivisionError already handled by
        # the `if decided else 0.0` guards, but assert the *values* too).
        assert not math.isnan(summary["win_rate"])
        assert not math.isinf(summary["win_rate"])

    def test_all_wins_is_exactly_100_not_more(self):
        trades = [_trade("win", r=1.0) for _ in range(5)]
        summary = _summarize(trades)
        assert summary["win_rate"] == 100.0
        assert summary["raw_win_rate"] == 100.0

    def test_all_losses_is_exactly_zero(self):
        trades = [_trade("loss", r=-1.0) for _ in range(5)]
        summary = _summarize(trades)
        assert summary["win_rate"] == 0.0
        assert summary["raw_win_rate"] == 0.0

    def test_win_rate_never_exceeds_100_across_many_mixes(self):
        # Sweep a range of win/loss/expired combinations — the exact
        # scenario class that produced "4740%" downstream (a mix that
        # nets out to ~47.4% got corrupted by a second *100 in the UI).
        for wins in range(0, 8):
            for losses in range(0, 8):
                for expired in range(0, 8):
                    trades = (
                        [_trade("win", r=1.0) for _ in range(wins)]
                        + [_trade("loss", r=-1.0) for _ in range(losses)]
                        + [_trade("expired") for _ in range(expired)]
                    )
                    summary = _summarize(trades)
                    assert 0.0 <= summary["win_rate"] <= 100.0, summary
                    assert 0.0 <= summary["raw_win_rate"] <= 100.0, summary

    def test_decided_excludes_expired_raw_includes_expired(self):
        # 3 wins, 1 loss, 6 expired/undecided.
        trades = (
            [_trade("win", r=1.0) for _ in range(3)]
            + [_trade("loss", r=-1.0)]
            + [_trade("expired") for _ in range(6)]
        )
        summary = _summarize(trades)
        assert summary["trades"] == 10
        assert summary["wins"] == 3
        assert summary["losses"] == 1
        assert summary["expired"] == 6
        # Directional: 3 / (3+1) * 100 = 75.0
        assert summary["win_rate"] == 75.0
        # Raw: 3 / 10 * 100 = 30.0
        assert summary["raw_win_rate"] == 30.0

    def test_counts_sum_to_total(self):
        trades = (
            [_trade("win", r=1.0) for _ in range(4)]
            + [_trade("loss", r=-1.0) for _ in range(2)]
            + [_trade("expired") for _ in range(3)]
        )
        summary = _summarize(trades)
        assert summary["wins"] + summary["losses"] + summary["expired"] == summary["trades"]

    def test_profit_factor_with_no_losing_trades_does_not_raise(self):
        # gross_loss == 0 must not raise ZeroDivisionError.
        trades = [_trade("win", r=1.0), _trade("win", r=2.0)]
        summary = _summarize(trades)
        assert summary["profit_factor"] == 3.0  # falls back to gross_win

    def test_profit_factor_with_no_trades_at_all_is_zero(self):
        summary = _summarize([])
        assert summary["profit_factor"] == 0.0

    def test_win_rate_is_already_percentage_scale_not_fraction(self):
        # Documents the exact contract the frontend must honor: win_rate
        # is 0-100, NOT 0-1. Multiplying it by 100 again (the actual bug
        # reported: a real 47.4% became "4740%") is a frontend error, not
        # something this function should compensate for.
        trades = [_trade("win", r=1.0) for _ in range(47)] + [_trade("loss", r=-1.0) for _ in range(53)]
        summary = _summarize(trades)
        assert summary["win_rate"] == 47.0
        assert summary["win_rate"] > 1.0  # i.e. not a 0-1 fraction
