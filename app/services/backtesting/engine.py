"""Backtesting engine: replays historical data through signal engine and tracks results."""
import logging
import numpy as np
import pandas as pd
from datetime import datetime

from app.services.signals.engine import signal_engine

logger = logging.getLogger(__name__)


class BacktestEngine:

    def run(self, df: pd.DataFrame, asset, timeframe: str,
            initial_capital: float = 100000) -> dict:
        """Run backtest and return full statistics."""
        if df is None or len(df) < 100:
            return {"error": "Insufficient data for backtesting"}

        trades = []
        equity = [initial_capital]
        capital = initial_capital
        position = None

        window = 60
        for i in range(window, len(df) - 1):
            window_df = df.iloc[i - window:i + 1].copy()
            signal = signal_engine.generate_signal(window_df, asset.symbol, timeframe)

            if signal is None:
                equity.append(capital)
                continue

            row = df.iloc[i]
            price = float(row["close"])

            # Close open position if signal reverses or SL/TP hit
            if position:
                closed, pnl_pct = self._check_close(position, price, df.iloc[i])
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

            # Open new position
            if position is None and signal["confidence_score"] >= 60:
                if signal["signal_type"] in ("BUY", "SELL"):
                    position = {
                        "type": signal["signal_type"],
                        "entry": price,
                        "stop_loss": signal["stop_loss"],
                        "target1": signal["target1"],
                        "target2": signal["target2"],
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
