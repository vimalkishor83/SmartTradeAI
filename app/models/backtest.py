from datetime import datetime
from app.extensions import db


class Backtest(db.Model):
    __tablename__ = "backtests"

    id = db.Column(db.Integer, primary_key=True)
    # Indexed: list_backtests() filters by user_id and sorts by created_at on
    # every call (app/api/v1/backtesting.py) — Signal/Notification/AuditLog
    # already have equivalent indexes for the same access pattern; Backtest
    # was missing them.
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"))
    strategy_name = db.Column(db.String(100))
    timeframe = db.Column(db.String(10))
    start_date = db.Column(db.DateTime)
    end_date = db.Column(db.DateTime)
    initial_capital = db.Column(db.Float, default=100000)
    status = db.Column(db.String(20), default="pending")  # pending, running, completed, failed

    # Results
    total_trades = db.Column(db.Integer, default=0)
    winning_trades = db.Column(db.Integer, default=0)
    losing_trades = db.Column(db.Integer, default=0)
    win_rate = db.Column(db.Float, default=0)
    net_profit = db.Column(db.Float, default=0)
    net_profit_pct = db.Column(db.Float, default=0)
    max_drawdown = db.Column(db.Float, default=0)
    sharpe_ratio = db.Column(db.Float, default=0)
    sortino_ratio = db.Column(db.Float, default=0)
    profit_factor = db.Column(db.Float, default=0)
    avg_win = db.Column(db.Float, default=0)
    avg_loss = db.Column(db.Float, default=0)
    avg_bars_held = db.Column(db.Float, default=0)
    total_commission = db.Column(db.Float, default=0)
    total_slippage = db.Column(db.Float, default=0)
    commission_pct = db.Column(db.Float, default=0.1)
    slippage_pct = db.Column(db.Float, default=0.05)
    exit_reasons = db.Column(db.JSON, default=dict)
    equity_curve = db.Column(db.JSON, default=list)
    trades_data = db.Column(db.JSON, default=list)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    completed_at = db.Column(db.DateTime)

    asset = db.relationship("Asset")

    def to_dict(self):
        return {
            "id": self.id,
            "asset": self.asset.symbol if self.asset else None,
            "strategy": self.strategy_name,
            "timeframe": self.timeframe,
            "status": self.status,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "net_profit": self.net_profit,
            "max_drawdown": self.max_drawdown,
            "sharpe_ratio":    self.sharpe_ratio,
            "sortino_ratio":   self.sortino_ratio,
            "profit_factor":   self.profit_factor,
            "avg_win":         self.avg_win,
            "avg_loss":        self.avg_loss,
            "avg_bars_held":   self.avg_bars_held,
            "total_commission":self.total_commission,
            "total_slippage":  self.total_slippage,
            "commission_pct":  self.commission_pct,
            "slippage_pct":    self.slippage_pct,
            "exit_reasons":    self.exit_reasons,
            "created_at":      self.created_at.isoformat(),
        }
