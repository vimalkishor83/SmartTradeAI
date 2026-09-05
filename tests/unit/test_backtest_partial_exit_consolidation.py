"""
Regression tests for partial-TP (T1 scale-out) trade consolidation in the
strategy-config backtest engine (app/services/backtesting/engine.py).

Real bug found during a backtesting-correctness audit: a single signal
that took a 50% partial exit at T1 appended TWO independent rows to the
engine's trade list (see BacktestEngine.run_backtest, "target1_partial"
then the eventual close of the remaining 50%). _compute_stats() classified
each row's win/loss independently and counted both toward total_trades —
so one net-profitable signal that banked a real gain at T1 and then gave
a little back to a breakeven-minus-costs stop on the runner was reported
as "1 win + 1 loss" instead of one winning trade, silently understating
the strategy's true win rate and inflating its trade count whenever T1
partials fired. _consolidate_trades() merges same-position legs (same
entry_bar_index) into one logical trade for every aggregate stat, while
the raw per-fill rows are still returned verbatim in trades_data for
full audit detail.
"""
import pandas as pd

from app.services.backtesting.engine import BacktestEngine, _consolidate_trades

engine = BacktestEngine()


def _leg(entry_bar_index, pnl, outcome, bars_held, exit_reason, leg_units=1.0,
         entry=100.0, exit_=105.0, commission=1.0, slippage_cost=0.5, date="2026-01-01"):
    return {
        "entry": entry, "exit": exit_, "type": "BUY", "bars_held": bars_held,
        "exit_reason": exit_reason, "pnl_pct": round(pnl / (entry * leg_units) * 100, 3) if entry else 0.0,
        "pnl": pnl, "commission": commission, "slippage_cost": slippage_cost,
        "outcome": outcome, "date": date,
        "entry_bar_index": entry_bar_index, "leg_units": leg_units,
    }


class TestConsolidateTrades:
    def test_single_leg_trade_passes_through_unchanged(self):
        # The common case (no partial exit at all) must be byte-for-byte
        # unaffected by consolidation.
        leg = _leg(10, pnl=50.0, outcome="win", bars_held=5, exit_reason="target2")
        result = _consolidate_trades([leg])
        assert len(result) == 1
        assert result[0] == leg

    def test_partial_win_plus_runner_small_loss_nets_to_one_win(self):
        # This is the exact reported scenario: T1 partial banks a real gain
        # (a "win" leg), the remainder later stops out at breakeven minus
        # costs (a "loss" leg) -- but the SIGNAL overall was net profitable.
        partial = _leg(10, pnl=30.0, outcome="win", bars_held=3, exit_reason="target1_partial", leg_units=0.5)
        final   = _leg(10, pnl=-5.0, outcome="loss", bars_held=8, exit_reason="stop_loss", leg_units=0.5)
        result = _consolidate_trades([partial, final])
        assert len(result) == 1  # one signal, not two independent trades
        trade = result[0]
        assert trade["pnl"] == 25.0          # 30 - 5, the TRUE net outcome
        assert trade["outcome"] == "win"      # net-positive -> win, not "1 win + 1 loss"
        assert trade["had_partial_exit"] is True
        assert trade["exit_reason"] == "stop_loss"  # what the position actually finished on
        assert trade["bars_held"] == 8         # full duration, not double-counted (3+8)

    def test_partial_win_plus_runner_bigger_loss_nets_to_one_loss(self):
        partial = _leg(20, pnl=10.0, outcome="win", bars_held=2, exit_reason="target1_partial", leg_units=0.5)
        final   = _leg(20, pnl=-40.0, outcome="loss", bars_held=15, exit_reason="stop_loss", leg_units=0.5)
        result = _consolidate_trades([partial, final])
        assert len(result) == 1
        assert result[0]["pnl"] == -30.0
        assert result[0]["outcome"] == "loss"

    def test_commission_and_slippage_are_summed_across_legs(self):
        partial = _leg(5, pnl=10.0, outcome="win", bars_held=1, exit_reason="target1_partial",
                        leg_units=0.5, commission=2.0, slippage_cost=1.0)
        final   = _leg(5, pnl=15.0, outcome="win", bars_held=4, exit_reason="target2",
                        leg_units=0.5, commission=3.0, slippage_cost=1.5)
        result = _consolidate_trades([partial, final])
        assert result[0]["commission"] == 5.0
        assert result[0]["slippage_cost"] == 2.5

    def test_multiple_independent_positions_stay_separate(self):
        # Two entirely different signals (different entry_bar_index) must
        # never be merged into each other.
        pos1 = _leg(1, pnl=10.0, outcome="win", bars_held=2, exit_reason="target2")
        pos2 = _leg(2, pnl=-10.0, outcome="loss", bars_held=3, exit_reason="stop_loss")
        result = _consolidate_trades([pos1, pos2])
        assert len(result) == 2

    def test_rows_with_no_entry_bar_index_are_not_incorrectly_grouped(self):
        # Defensive: two unrelated legacy-shaped rows sharing a `None` key
        # must not be merged into one fictitious "trade".
        a = {"entry": 100, "exit": 105, "type": "BUY", "bars_held": 1,
             "exit_reason": "target2", "pnl_pct": 5.0, "pnl": 10.0,
             "commission": 1.0, "slippage_cost": 0.5, "outcome": "win", "date": "d1"}
        b = {**a, "pnl": -10.0, "outcome": "loss", "date": "d2"}
        result = _consolidate_trades([a, b])
        assert len(result) == 2


class TestComputeStatsWithPartialExits:
    def test_win_rate_reflects_consolidated_signals_not_raw_fills(self):
        # 2 signals total: signal A = partial-win + runner-small-loss (nets
        # to one win); signal B = a clean single-leg loss. True win rate is
        # 1/2 = 50%, and total_trades must read 2, not 3 raw fills.
        a_partial = _leg(1, pnl=30.0, outcome="win", bars_held=2, exit_reason="target1_partial", leg_units=0.5)
        a_final   = _leg(1, pnl=-5.0, outcome="loss", bars_held=6, exit_reason="stop_loss", leg_units=0.5)
        b_single  = _leg(2, pnl=-20.0, outcome="loss", bars_held=4, exit_reason="stop_loss")
        trades = [a_partial, a_final, b_single]
        equity = [10_000.0, 10_005.0]  # exact values irrelevant to this assertion
        stats = engine._compute_stats(trades, equity, 10_000.0, 0.001, 0.0005, "1h")

        assert stats["total_trades"] == 2      # not 3
        assert stats["winning_trades"] == 1
        assert stats["losing_trades"] == 1
        assert stats["win_rate"] == 50.0        # not 33.3 (1/3, the pre-fix bug)
        assert 0.0 <= stats["win_rate"] <= 100.0
        # Full per-fill audit trail is preserved verbatim regardless.
        assert len(stats["trades_data"]) == 3

    def test_zero_trades_still_returns_zero_not_error(self):
        stats = engine._compute_stats([], [10_000.0], 10_000.0, 0.001, 0.0005, "1h")
        assert stats["total_trades"] == 0
        assert stats["win_rate"] == 0


def test_end_of_data_close_includes_entry_and_exit_slippage(monkeypatch):
    """A forced final-bar exit must report both sides of slippage."""
    frame = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0},
        index=pd.date_range("2026-01-01", periods=100, freq="h"),
    )

    monkeypatch.setattr(
        engine,
        "_signal_rsi",
        lambda closes, rsi, index: "BUY" if index == 60 else None,
    )
    monkeypatch.setattr(
        engine,
        "_manage_position",
        lambda *args: (False, 0.0, "", 0.0),
    )

    result = engine.run(
        frame,
        asset=None,
        timeframe="1h",
        initial_capital=10_000,
        strategy="rsi",
        commission=0.0,
        slippage=0.0005,
    )

    trade = result["trades_data"][0]
    expected = round(
        (abs(trade["entry"] - 100.0) + abs(trade["exit"] - 100.0))
        * trade["leg_units"],
        2,
    )
    assert trade["exit_reason"] == "end_of_data"
    assert trade["slippage_cost"] == expected
    assert result["total_slippage"] == expected
