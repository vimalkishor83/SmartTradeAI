"""
Backtesting engine — realistic simulation with commission, slippage,
position sizing, max hold time, and per-trade metrics.

Improvements over original:
  1. Commission deducted on every entry AND exit (configurable, default 0.1%)
  2. Slippage applied to all fill prices (configurable, default 0.05%)
  3. Volatility-adjusted position sizing — smaller size in high-ATR regimes
  4. Max bars hold limit per timeframe — forces close of stale trades
  5. No re-entry on same bar a trade closed (prevents look-ahead bias)
  6. Partial target: scale out 50% at T1, move SL to breakeven, ride to T2
  7. Confidence filter for multi_factor strategy raised to 70 (matches live engine)
  8. ATR pre-computed once for the full DataFrame (not per-window)
  9. Separate MAE/MFE tracked per trade (max adverse / max favourable excursion)
 10. Sortino ratio added to stats (penalises only downside volatility)
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Realistic defaults ──────────────────────────────────────────────────────
DEFAULT_COMMISSION  = 0.001   # 0.10% per side (entry + exit)
DEFAULT_SLIPPAGE    = 0.0005  # 0.05% of price — market-order assumption

# Max candles a trade can stay open before force-closing
MAX_HOLD_BARS: dict[str, int] = {
    "1m": 30, "5m": 24, "15m": 16, "30m": 12,
    "1h": 10,  "2h": 8,  "4h": 6,  "1d": 5,
}

# Minimum confidence to enter a multi_factor trade (matches live pipeline)
MIN_CONFIDENCE = 70


class BacktestEngine:

    # ── Indicator helpers (self-contained, no external imports) ────────────

    def _rsi(self, closes: pd.Series, period: int = 14) -> pd.Series:
        delta = closes.diff()
        gain  = delta.clip(lower=0).rolling(period).mean()
        loss  = (-delta.clip(upper=0)).rolling(period).mean()
        rs    = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def _ema(self, closes: pd.Series, span: int) -> pd.Series:
        return closes.ewm(span=span, adjust=False).mean()

    def _macd(self, closes: pd.Series):
        fast   = self._ema(closes, 12)
        slow   = self._ema(closes, 26)
        line   = fast - slow
        signal = self._ema(line, 9)
        return line, signal

    def _atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        c = df["close"].astype(float)
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def _sl_tp(self, price: float, direction: str, atr: float):
        dist = max(atr * 1.5, price * 0.005)
        if direction == "BUY":
            return price - dist, price + dist * 1.5, price + dist * 3.0
        return price + dist, price - dist * 1.5, price - dist * 3.0

    # ── Entry signal generators ─────────────────────────────────────────────
    # Previously each of these recomputed its indicator (RSI / MACD /
    # EMA20+EMA50) over the ENTIRE closes series from bar 0, on EVERY
    # single loop iteration, discarding everything except .iloc[i] — O(n^2)
    # total indicator work for an O(n) backtest. _atr was already fixed
    # this way (computed once in run(), see atr_ser); these three now
    # follow the same pattern: pre-compute the full indicator series once
    # in run() and pass it in, so each per-bar call is an O(1) lookup.

    def _signal_rsi(self, closes: pd.Series, rsi: pd.Series, i: int) -> str | None:
        if i < 20:
            return None
        if rsi.iloc[i] < 30 and closes.iloc[i] > closes.iloc[i - 1]:
            return "BUY"
        if rsi.iloc[i] > 70 and closes.iloc[i] < closes.iloc[i - 1]:
            return "SELL"
        return None

    def _signal_macd(self, line: pd.Series, sig: pd.Series, i: int) -> str | None:
        if i < 35:
            return None
        prev = line.iloc[i - 1] - sig.iloc[i - 1]
        curr = line.iloc[i]     - sig.iloc[i]
        if prev < 0 and curr >= 0:
            return "BUY"
        if prev > 0 and curr <= 0:
            return "SELL"
        return None

    def _signal_ema_cross(self, ema20: pd.Series, ema50: pd.Series, i: int) -> str | None:
        if i < 55:
            return None
        prev = ema20.iloc[i - 1] - ema50.iloc[i - 1]
        curr = ema20.iloc[i]     - ema50.iloc[i]
        if prev < 0 and curr >= 0:
            return "BUY"
        if prev > 0 and curr <= 0:
            return "SELL"
        return None

    # ── Fill price with slippage ────────────────────────────────────────────

    @staticmethod
    def _fill_price(price: float, direction: str, slippage: float) -> float:
        """Apply slippage: BUY fills higher, SELL fills lower."""
        if direction == "BUY":
            return price * (1 + slippage)
        return price * (1 - slippage)

    # ── Volatility regime scalar ────────────────────────────────────────────

    @staticmethod
    def _vol_scalar(cur_atr: float, atr_series: pd.Series, i: int) -> float:
        """Scale position size based on ATR percentile (last 50 bars)."""
        window = atr_series.iloc[max(0, i - 50):i].dropna()
        if len(window) < 5:
            return 1.0
        pct = float((window <= cur_atr).mean())
        if pct > 0.80:
            return 0.50
        if pct > 0.60:
            return 0.75
        return 1.00

    # ── Main run ────────────────────────────────────────────────────────────

    def run(
        self,
        df: pd.DataFrame,
        asset,
        timeframe: str,
        initial_capital: float = 100_000,
        strategy: str = "multi_factor",
        commission: float = DEFAULT_COMMISSION,
        slippage: float = DEFAULT_SLIPPAGE,
    ) -> dict:
        if df is None or len(df) < 100:
            return {"error": "Insufficient data for backtesting (need ≥100 candles)"}

        closes  = df["close"].astype(float).reset_index(drop=True)
        highs   = df["high"].astype(float).reset_index(drop=True)
        lows    = df["low"].astype(float).reset_index(drop=True)
        df_r    = df.reset_index(drop=True)
        atr_ser = self._atr(df_r)

        max_hold  = MAX_HOLD_BARS.get(timeframe, 10)
        use_engine = (strategy == "multi_factor")
        warmup     = 60

        # Pre-compute whatever indicator series this strategy needs ONCE
        # over the full df, rather than inside the per-bar loop — see the
        # _signal_* docstring note above. multi_factor doesn't use these
        # (it goes through signal_engine.generate_signal instead, which
        # has its own separate indicator computation — see the run()
        # multi_factor branch below for that fix).
        rsi_ser = ema20_ser = ema50_ser = macd_line = macd_signal = None
        if strategy == "rsi":
            rsi_ser = self._rsi(closes)
        elif strategy == "macd":
            macd_line, macd_signal = self._macd(closes)
        elif strategy == "ema_crossover":
            ema20_ser = self._ema(closes, 20)
            ema50_ser = self._ema(closes, 50)

        trades:    list[dict[str, Any]] = []
        equity:    list[float]          = [initial_capital] * warmup
        capital    = initial_capital
        position   = None
        last_close_bar = -1   # prevent re-entry on same bar

        for i in range(warmup, len(df_r) - 1):
            price   = float(closes.iloc[i])
            cur_atr = float(atr_ser.iloc[i]) if not np.isnan(atr_ser.iloc[i]) else price * 0.01
            vol_s   = self._vol_scalar(cur_atr, atr_ser, i)

            # ── Determine new signal direction ─────────────────────────────
            direction = sl = t1 = t2 = None

            if use_engine:
                from app.services.signals.engine import signal_engine
                # generate_signal() never mutates its df argument (verified:
                # only .iloc[-1]/.rolling()/.pct_change()-style read access
                # throughout signals/engine.py) -- the .copy() here was pure
                # unnecessary per-bar allocation overhead, dropped.
                win  = df_r.iloc[max(0, i - warmup): i + 1]
                # Pass a minimal asset-like object — engine only reads .market
                sig  = signal_engine.generate_signal(win, asset, timeframe)
                if sig and sig["confidence_score"] >= MIN_CONFIDENCE \
                        and sig["signal_type"] in ("BUY", "SELL"):
                    direction = sig["signal_type"]
                    sl  = sig["stop_loss"]
                    t1  = sig["target1"]
                    t2  = sig["target2"]
            else:
                if strategy == "rsi":
                    direction = self._signal_rsi(closes, rsi_ser, i)
                elif strategy == "macd":
                    direction = self._signal_macd(macd_line, macd_signal, i)
                elif strategy == "ema_crossover":
                    direction = self._signal_ema_cross(ema20_ser, ema50_ser, i)
                if direction:
                    sl, t1, t2 = self._sl_tp(price, direction, cur_atr)

            # ── Manage open position ───────────────────────────────────────
            if position:
                closed, exit_price, exit_reason, partial_units = self._manage_position(
                    position, price, highs.iloc[i], lows.iloc[i],
                    direction, i, max_hold,
                )
                if partial_units:
                    # Book P&L on the 50% scaled out at T1 right now — the
                    # remaining units stay open and continue to SL/T2/timeout.
                    # This used to be a documented "simplification" (see class
                    # docstring point 6) where the SL moved to breakeven at T1
                    # but the FULL position rode to T2 — meaning the backtest
                    # never actually realized the T1 partial the Help page
                    # tells users to expect ("50% closed at T1"). Every
                    # win-rate/profit-factor number reported from a backtest
                    # was silently overstating the T1->T2 leg's contribution.
                    partial_fill = self._fill_price(exit_price, _opposite(position["type"]), slippage)
                    partial_comm = partial_fill * partial_units * commission
                    if position["type"] == "BUY":
                        partial_gross = (partial_fill - position["fill"]) * partial_units
                    else:
                        partial_gross = (position["fill"] - partial_fill) * partial_units
                    # Entry commission is prorated to the portion being closed now.
                    partial_entry_comm = position["entry_commission"] * (partial_units / position["units"])
                    partial_net = partial_gross - partial_comm - partial_entry_comm
                    capital += partial_net
                    trades.append({
                        "entry":        round(position["fill"], 6),
                        "exit":         round(partial_fill, 6),
                        "type":         position["type"],
                        "bars_held":    i - position["bar_index"],
                        "exit_reason":  "target1_partial",
                        "pnl_pct":      round(partial_net / (position["fill"] * partial_units) * 100, 3),
                        "pnl":          round(partial_net, 2),
                        "commission":   round(partial_comm + partial_entry_comm, 2),
                        "slippage_cost":round(abs(partial_fill - exit_price) * partial_units, 2),
                        "outcome":      "win" if partial_net > 0 else "loss",
                        "date":         str(df.index[i]) if hasattr(df.index[i], "__str__") else str(i),
                        # Links this leg to its eventual final-close leg (same
                        # entry_bar_index) so _compute_stats can consolidate
                        # one signal's two fills into one logical trade for
                        # win_rate/total_trades/etc, instead of double-counting
                        # a single profitable signal as "1 win + 1 loss" when
                        # the remainder later closes at a small breakeven-minus-
                        # costs loss. See _consolidate_trades().
                        "entry_bar_index": position["bar_index"],
                        "leg_units":       partial_units,
                    })
                    # Shrink the remaining position — the rest still tracks
                    # toward T2/breakeven-SL/timeout with the smaller size.
                    position["units"] -= partial_units
                    position["entry_commission"] -= partial_entry_comm

                if closed:
                    exit_fill = self._fill_price(exit_price, _opposite(position["type"]), slippage)
                    comm_cost = exit_fill * position["units"] * commission
                    if position["type"] == "BUY":
                        gross_pnl = (exit_fill - position["fill"]) * position["units"]
                    else:
                        gross_pnl = (position["fill"] - exit_fill) * position["units"]
                    net_pnl = gross_pnl - comm_cost - position["entry_commission"]
                    pnl_pct = net_pnl / (position["fill"] * position["units"]) * 100

                    capital += net_pnl
                    last_close_bar = i
                    trades.append({
                        "entry":        round(position["fill"], 6),
                        "exit":         round(exit_fill, 6),
                        "type":         position["type"],
                        "bars_held":    i - position["bar_index"],
                        "exit_reason":  exit_reason,
                        "pnl_pct":      round(pnl_pct, 3),
                        "pnl":          round(net_pnl, 2),
                        "commission":   round(comm_cost + position["entry_commission"], 2),
                        "slippage_cost":round(position["slippage_cost"] + abs(exit_fill - exit_price) * position["units"], 2),
                        "outcome":      "win" if net_pnl > 0 else "loss",
                        "date":         str(df.index[i]) if hasattr(df.index[i], "__str__") else str(i),
                        "entry_bar_index": position["bar_index"],
                        "leg_units":       position["units"],
                    })
                    position = None

            # ── Open new position ──────────────────────────────────────────
            if position is None and direction and sl and t1 and t2 and i != last_close_bar:
                fill   = self._fill_price(price, direction, slippage)
                # Risk 1% of capital per trade, scaled by volatility regime
                risk_amt  = capital * 0.01 * vol_s
                risk_unit = abs(fill - sl)
                units     = (risk_amt / risk_unit) if risk_unit > 0 else 0
                if units <= 0:
                    equity.append(capital)
                    continue

                entry_comm   = fill * units * commission
                slippage_pct = abs(fill - price) * units
                capital     -= entry_comm   # deduct entry commission immediately

                position = {
                    "type":               direction,
                    "entry":              price,
                    "fill":               fill,
                    "stop_loss":          sl,
                    "target1":            t1,
                    "target2":            t2,
                    "units":              units,
                    "bar_index":          i,
                    "entry_commission":   entry_comm,
                    "slippage_cost":      slippage_pct,
                    "sl_moved_to_be":     False,   # breakeven flag
                    "partial_taken":      False,    # T1 partial exit flag
                }

            equity.append(round(capital, 2))

        # Force-close any open position at last available price
        if position:
            last_price = float(closes.iloc[-1])
            exit_fill  = self._fill_price(last_price, _opposite(position["type"]), slippage)
            comm_cost  = exit_fill * position["units"] * commission
            if position["type"] == "BUY":
                gross_pnl = (exit_fill - position["fill"]) * position["units"]
            else:
                gross_pnl = (position["fill"] - exit_fill) * position["units"]
            net_pnl = gross_pnl - comm_cost - position["entry_commission"]
            pnl_pct = net_pnl / (position["fill"] * position["units"]) * 100
            capital += net_pnl
            trades.append({
                "entry": round(position["fill"], 6), "exit": round(exit_fill, 6),
                "type": position["type"], "bars_held": len(df_r) - position["bar_index"],
                "exit_reason": "end_of_data", "pnl_pct": round(pnl_pct, 3),
                "pnl": round(net_pnl, 2), "commission": round(comm_cost + position["entry_commission"], 2),
                "slippage_cost": round(
                    position["slippage_cost"]
                    + abs(exit_fill - last_price) * position["units"],
                    2,
                ),
                "outcome": "win" if net_pnl > 0 else "loss",
                "date": str(df.index[-1]),
                "entry_bar_index": position["bar_index"],
                "leg_units":       position["units"],
            })
            equity.append(round(capital, 2))

        return self._compute_stats(
            trades, equity, initial_capital, commission, slippage, timeframe
        )

    # ── Position management (SL / T1 partial / T2 / timeout) ───────────────

    def _manage_position(
        self,
        pos: dict,
        price: float,
        high: float,
        low: float,
        new_direction: str | None,
        bar_index: int,
        max_hold: int,
    ) -> tuple[bool, float, str, float]:
        """
        Returns (closed, exit_price, reason, partial_units).
        Implements:
          - SL hit on bar high/low (intra-bar check)
          - Partial exit at T1: 50% of units booked now (partial_units > 0),
            SL moved to breakeven on the remainder, position stays open
          - Full exit at T2 (on whatever units remain — the other 50% if T1
            already hit, or the full size if price gapped straight to T2)
          - Signal reversal closes immediately
          - Max hold timeout
        """
        ptype = pos["type"]
        sl    = pos["stop_loss"]
        t1    = pos["target1"]
        t2    = pos["target2"]
        entry = pos["fill"]

        if ptype == "BUY":
            # Stop hit (use intra-bar low)
            if low <= sl:
                return True, sl, "stop_loss", 0.0
            # T2 hit
            if high >= t2:
                return True, t2, "target2", 0.0
            # T1 partial — book 50% now, move SL to breakeven on the rest
            if not pos["partial_taken"] and high >= t1:
                pos["partial_taken"]  = True
                pos["sl_moved_to_be"] = True
                pos["stop_loss"]      = entry    # breakeven SL
                return False, t1, "target1_partial", pos["units"] * 0.5
        else:  # SELL
            if high >= sl:
                return True, sl, "stop_loss", 0.0
            if low <= t2:
                return True, t2, "target2", 0.0
            if not pos["partial_taken"] and low <= t1:
                pos["partial_taken"]  = True
                pos["sl_moved_to_be"] = True
                pos["stop_loss"]      = entry
                return False, t1, "target1_partial", pos["units"] * 0.5

        # Signal reversal
        if new_direction and new_direction != ptype:
            return True, price, "signal_reversal", 0.0

        # Max hold timeout
        if bar_index - pos["bar_index"] >= max_hold:
            return True, price, "timeout", 0.0

        return False, price, "", 0.0

    # ── Statistics ──────────────────────────────────────────────────────────

    def _compute_stats(
        self,
        trades: list,
        equity: list,
        initial_capital: float,
        commission: float,
        slippage: float,
        timeframe: str,
    ) -> dict:
        if not trades:
            return {
                "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
                "win_rate": 0, "net_profit": 0, "net_profit_pct": 0,
                "max_drawdown": 0, "sharpe_ratio": 0, "sortino_ratio": 0,
                "profit_factor": 0, "avg_win": 0, "avg_loss": 0,
                "avg_bars_held": 0, "total_commission": 0, "total_slippage": 0,
                "commission_pct": commission * 100, "slippage_pct": slippage * 100,
                "equity_curve": equity[-500:], "trades_data": [],
            }

        # A single signal that scales out 50% at T1 (see _manage_position)
        # appends TWO rows to `trades`: the T1 partial fill, then the
        # eventual close of the remaining half. Every aggregate stat below
        # (win_rate, total_trades, avg_win/loss, profit_factor, sharpe,
        # sortino) must describe *signals*, not *fills* — otherwise a single
        # net-profitable signal that banked a real gain at T1 and then gave
        # a few points back to a breakeven-minus-costs stop on the runner
        # gets counted as "1 win + 1 loss", silently understating the
        # strategy's true win rate. _consolidate_trades merges same-position
        # legs into one logical trade for every stat computed from here on;
        # `trades_data` below still returns the raw, per-fill rows verbatim
        # so the trade-list UI keeps showing both legs for full audit detail.
        stat_trades = _consolidate_trades(trades)

        wins   = [t for t in stat_trades if t["outcome"] == "win"]
        losses = [t for t in stat_trades if t["outcome"] == "loss"]

        final_capital = equity[-1]
        net_profit    = final_capital - initial_capital
        net_pct       = (net_profit / initial_capital) * 100
        win_rate      = len(wins) / len(stat_trades) * 100

        avg_win  = float(np.mean([t["pnl_pct"] for t in wins]))   if wins   else 0
        avg_loss = float(np.mean([t["pnl_pct"] for t in losses]))  if losses else 0

        gross_wins  = sum(t["pnl"] for t in wins)
        gross_losses = abs(sum(t["pnl"] for t in losses))
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else 999.0

        # Commission/slippage are additive regardless of how a position's
        # fills get grouped, so summing the raw per-fill rows here gives the
        # identical (and simpler-to-verify) total to summing stat_trades.
        total_comm     = sum(t.get("commission", 0)    for t in trades)
        total_slippage = sum(t.get("slippage_cost", 0) for t in trades)
        avg_hold       = float(np.mean([t.get("bars_held", 0) for t in stat_trades]))

        # Equity drawdown
        eq = pd.Series(equity)
        rolling_max  = eq.cummax()
        drawdown     = (eq - rolling_max) / rolling_max
        max_drawdown = float(drawdown.min() * 100)

        # Exit reason breakdown — per consolidated signal (a signal that
        # took a T1 partial then hit its final stop is "stop_loss", the
        # reason it actually finished on, not double-counted as both
        # "target1_partial" and "stop_loss").
        reasons: dict[str, int] = {}
        for t in stat_trades:
            r = t.get("exit_reason", "unknown")
            reasons[r] = reasons.get(r, 0) + 1

        # Annualised Sharpe and Sortino — per-signal returns, not per-fill.
        ret_series = pd.Series([t["pnl_pct"] for t in stat_trades])
        bars_per_year = _bars_per_year(timeframe)
        if len(ret_series) > 1 and ret_series.std() > 0:
            sharpe = float(ret_series.mean() / ret_series.std()) * np.sqrt(bars_per_year)
        else:
            sharpe = 0.0
        downside = ret_series[ret_series < 0]
        if len(downside) > 1 and downside.std() > 0:
            sortino = float(ret_series.mean() / downside.std()) * np.sqrt(bars_per_year)
        else:
            sortino = 0.0

        return {
            "total_trades":     len(stat_trades),
            "winning_trades":   len(wins),
            "losing_trades":    len(losses),
            "win_rate":         round(win_rate, 1),
            "net_profit":       round(net_profit, 2),
            "net_profit_pct":   round(net_pct, 2),
            "max_drawdown":     round(max_drawdown, 2),
            "sharpe_ratio":     round(sharpe, 2),
            "sortino_ratio":    round(sortino, 2),
            "profit_factor":    round(min(profit_factor, 999), 2),
            "avg_win":          round(avg_win, 2),
            "avg_loss":         round(avg_loss, 2),
            "avg_bars_held":    round(avg_hold, 1),
            "total_commission": round(total_comm, 2),
            "total_slippage":   round(total_slippage, 2),
            "commission_pct":   round(commission * 100, 3),
            "slippage_pct":     round(slippage * 100, 3),
            "exit_reasons":     reasons,
            "equity_curve":     [round(e, 2) for e in equity[-500:]],
            "trades_data":      trades[-100:],
        }


# ── Helpers ─────────────────────────────────────────────────────────────────

def _consolidate_trades(trades: list[dict]) -> list[dict]:
    """Merge a T1-partial-exit leg with its eventual final-close leg (same
    `entry_bar_index` — set on every trade dict appended in run_backtest())
    into one logical trade, so aggregate stats describe signals rather than
    fills. A trade with no partial exit (the common case) has exactly one
    leg and passes through unchanged. Rows with no `entry_bar_index` at all
    (should not happen for trades produced by this engine, but tolerated
    defensively) are each treated as their own single-leg trade rather than
    silently dropped or incorrectly grouped together under a shared `None` key.
    """
    by_position: dict[Any, list[dict]] = {}
    solo: list[dict] = []
    for t in trades:
        key = t.get("entry_bar_index")
        if key is None:
            solo.append(t)
        else:
            by_position.setdefault(key, []).append(t)

    consolidated: list[dict] = list(solo)
    for legs in by_position.values():
        if len(legs) == 1:
            consolidated.append(legs[0])
            continue
        total_pnl  = sum(l["pnl"] for l in legs)
        total_comm = sum(l.get("commission", 0) for l in legs)
        total_slip = sum(l.get("slippage_cost", 0) for l in legs)
        total_units = sum(l.get("leg_units", 0) for l in legs) or 1
        entry_price = legs[0]["entry"]  # identical across every leg of one position
        final_leg = legs[-1]            # last-appended leg is the one that actually closed the position
        consolidated.append({
            "entry":        entry_price,
            "exit":         final_leg["exit"],
            "type":         final_leg["type"],
            "bars_held":    max(l["bars_held"] for l in legs),
            "exit_reason":  final_leg["exit_reason"],
            "pnl_pct":      round(total_pnl / (entry_price * total_units) * 100, 3) if entry_price else 0.0,
            "pnl":          round(total_pnl, 2),
            "commission":   round(total_comm, 2),
            "slippage_cost":round(total_slip, 2),
            "outcome":      "win" if total_pnl > 0 else "loss",
            "date":         final_leg["date"],
            "had_partial_exit": True,
        })
    return consolidated


def _opposite(direction: str) -> str:
    return "SELL" if direction == "BUY" else "BUY"


def _bars_per_year(timeframe: str) -> float:
    """Approximate number of trading bars per year for Sharpe annualisation."""
    mapping = {
        "1m": 525_600, "5m": 105_120, "15m": 35_040, "30m": 17_520,
        "1h": 8_760,   "2h": 4_380,   "4h": 2_190,   "1d": 252,
    }
    return float(mapping.get(timeframe, 252))


backtest_engine = BacktestEngine()
