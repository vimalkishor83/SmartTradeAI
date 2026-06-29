"""Backtesting engine: replays historical data through signal engine and tracks results."""
import logging
import numpy as np
import pandas as pd
from datetime import datetime

from app.services.signals.engine import signal_engine

logger = logging.getLogger(__name__)


class BacktestEngine:

    # ── Strategy helpers ────────────────────────────────────────────────────

    def _rsi(self, closes: pd.Series, period: int = 14) -> pd.Series:
        delta = closes.diff()
        gain  = delta.clip(lower=0).rolling(period).mean()
        loss  = (-delta.clip(upper=0)).rolling(period).mean()
        rs    = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def _ema(self, closes: pd.Series, span: int) -> pd.Series:
        return closes.ewm(span=span, adjust=False).mean()

    def _macd(self, closes: pd.Series):
        fast  = self._ema(closes, 12)
        slow  = self._ema(closes, 26)
        line  = fast - slow
        signal = self._ema(line, 9)
        return line, signal

    def _sl_tp(self, price: float, direction: str, atr: float):
        """Derive stop-loss / targets from ATR."""
        sl_dist = max(atr * 1.5, price * 0.005)
        if direction == "BUY":
            sl  = price - sl_dist
            t1  = price + sl_dist * 1.5
            t2  = price + sl_dist * 3.0
        else:
            sl  = price + sl_dist
            t1  = price - sl_dist * 1.5
            t2  = price - sl_dist * 3.0
        return sl, t1, t2

    # ── Entry signal generators ─────────────────────────────────────────────

    def _signal_rsi(self, closes: pd.Series, i: int) -> str | None:
        """RSI strategy: oversold/overbought with close direction confirmation."""
        if i < 20:
            return None
        rsi = self._rsi(closes)
        cur_rsi  = rsi.iloc[i]
        cur_cls  = closes.iloc[i]
        prev_cls = closes.iloc[i - 1]
        if cur_rsi < 30 and cur_cls > prev_cls:
            return "BUY"
        if cur_rsi > 70 and cur_cls < prev_cls:
            return "SELL"
        return None

    def _signal_macd(self, closes: pd.Series, i: int) -> str | None:
        """MACD crossover strategy."""
        if i < 35:
            return None
        macd_line, signal_line = self._macd(closes)
        prev_diff = macd_line.iloc[i - 1] - signal_line.iloc[i - 1]
        curr_diff = macd_line.iloc[i]     - signal_line.iloc[i]
        if prev_diff < 0 and curr_diff >= 0:
            return "BUY"
        if prev_diff > 0 and curr_diff <= 0:
            return "SELL"
        return None

    def _signal_ema_cross(self, closes: pd.Series, i: int) -> str | None:
        """EMA 20/50 crossover strategy."""
        if i < 55:
            return None
        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, 50)
        prev_diff = ema20.iloc[i - 1] - ema50.iloc[i - 1]
        curr_diff = ema20.iloc[i]     - ema50.iloc[i]
        if prev_diff < 0 and curr_diff >= 0:
            return "BUY"
        if prev_diff > 0 and curr_diff <= 0:
            return "SELL"
        return None

    # ── Main run method ─────────────────────────────────────────────────────

    def run(self, df: pd.DataFrame, asset, timeframe: str,
            initial_capital: float = 100000, strategy: str = "multi_factor") -> dict:
        """Run backtest and return full statistics."""
        if df is None or len(df) < 100:
            return {"error": "Insufficient data for backtesting"}

        trades  = []
        equity  = [initial_capital]
        capital = initial_capital
        position = None

        closes = df["close"].astype(float).reset_index(drop=True)
        # ATR for position sizing
        highs  = df["high"].astype(float).reset_index(drop=True)
        lows   = df["low"].astype(float).reset_index(drop=True)
        tr     = pd.concat([highs - lows,
                            (highs - closes.shift()).abs(),
                            (lows  - closes.shift()).abs()], axis=1).max(axis=1)
        atr    = tr.rolling(14).mean()

        use_engine = (strategy == "multi_factor")
        window     = 60

        for i in range(window, len(df) - 1):
            price = float(closes.iloc[i])
            cur_atr = float(atr.iloc[i]) if not np.isnan(atr.iloc[i]) else price * 0.01

            # ── Determine signal direction ──────────────────────────────────
            direction = None
            sl = t1 = t2 = None

            if use_engine:
                window_df = df.iloc[i - window:i + 1].copy()
                signal = signal_engine.generate_signal(window_df, asset.symbol, timeframe)
                if signal is None:
                    equity.append(capital)
                    continue
                if signal["confidence_score"] < 60 or signal["signal_type"] not in ("BUY", "SELL"):
                    equity.append(capital)
                    continue
                direction = signal["signal_type"]
                sl  = signal["stop_loss"]
                t1  = signal["target1"]
                t2  = signal["target2"]
            else:
                if strategy == "rsi":
                    direction = self._signal_rsi(closes, i)
                elif strategy == "macd":
                    direction = self._signal_macd(closes, i)
                elif strategy == "ema_crossover":
                    direction = self._signal_ema_cross(closes, i)

                if direction:
                    sl, t1, t2 = self._sl_tp(price, direction, cur_atr)

            # ── Check / close existing position ────────────────────────────
            if position:
                closed, pnl_pct = self._check_close(position, price, df.iloc[i])
                if not closed and direction and direction != position["type"]:
                    # Signal reversed — close at current price
                    if position["type"] == "BUY":
                        pnl_pct = (price - position["entry"]) / position["entry"] * 100
                    else:
                        pnl_pct = (position["entry"] - price) / position["entry"] * 100
                    closed = True
                if closed:
                    pnl = capital * (pnl_pct / 100)
                    capital += pnl
                    trades.append({
                        "entry": position["entry"],
                        "exit": price,
                        "type": position["type"],
                        "pnl_pct": pnl_pct,
                        "pnl": pnl,
                        "outcome": "win" if pnl > 0 else "loss",
                        "date": str(df.index[i]),
                    })
                    position = None

            # ── Open new position ───────────────────────────────────────────
            if position is None and direction and sl and t1 and t2:
                position = {
                    "type": direction,
                    "entry": price,
                    "stop_loss": sl,
                    "target1": t1,
                    "target2": t2,
                    "bar_index": i,
                }

            equity.append(capital)

        return self._compute_stats(trades, equity, initial_capital)

    def _check_close(self, pos, current_price, bar):
        ptype = pos["type"]
        sl = pos["stop_loss"]
        t1 = pos["target1"]
        t2 = pos["target2"]
        entry = pos["entry"]

        if ptype == "BUY":
            if bar["low"] <= sl:
                pnl_pct = ((sl - entry) / entry) * 100
                return True, pnl_pct
            if bar["high"] >= t2:
                pnl_pct = ((t2 - entry) / entry) * 100
                return True, pnl_pct
        elif ptype == "SELL":
            if bar["high"] >= sl:
                pnl_pct = ((entry - sl) / entry) * 100
                return True, pnl_pct
            if bar["low"] <= t2:
                pnl_pct = ((entry - t2) / entry) * 100
                return True, pnl_pct

        return False, 0

    def _compute_stats(self, trades: list, equity: list, initial_capital: float) -> dict:
        if not trades:
            return {
                "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
                "win_rate": 0, "net_profit": 0, "net_profit_pct": 0,
                "max_drawdown": 0, "sharpe_ratio": 0, "profit_factor": 0,
                "avg_win": 0, "avg_loss": 0,
                "equity_curve": equity[-200:], "trades_data": [],
            }

        wins = [t for t in trades if t["outcome"] == "win"]
        losses = [t for t in trades if t["outcome"] == "loss"]

        net_profit = equity[-1] - initial_capital
        net_pct = (net_profit / initial_capital) * 100
        win_rate = len(wins) / len(trades) * 100 if trades else 0

        avg_win = np.mean([t["pnl_pct"] for t in wins]) if wins else 0
        avg_loss = abs(np.mean([t["pnl_pct"] for t in losses])) if losses else 0
        profit_factor = (sum(t["pnl"] for t in wins) /
                         abs(sum(t["pnl"] for t in losses))) if losses else 999

        eq_series = pd.Series(equity)
        rolling_max = eq_series.cummax()
        drawdown = (eq_series - rolling_max) / rolling_max
        max_drawdown = float(drawdown.min() * 100)

        returns = pd.Series([t["pnl_pct"] for t in trades])
        sharpe = float(returns.mean() / returns.std()) * np.sqrt(252) if len(returns) > 1 and returns.std() > 0 else 0

        return {
            "total_trades": len(trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(win_rate, 1),
            "net_profit": round(net_profit, 2),
            "net_profit_pct": round(net_pct, 2),
            "max_drawdown": round(max_drawdown, 2),
            "sharpe_ratio": round(sharpe, 2),
            "profit_factor": round(min(profit_factor, 999), 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "equity_curve": [round(e, 2) for e in equity[-500:]],
            "trades_data": trades[-100:],
        }


backtest_engine = BacktestEngine()
