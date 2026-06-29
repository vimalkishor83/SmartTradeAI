from datetime import datetime
from app.extensions import db


class Backtest(db.Model):
    __tablename__ = "backtests"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
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
    profit_factor = db.Column(db.Float, default=0)
    avg_win = db.Column(db.Float, default=0)
    avg_loss = db.Column(db.Float, default=0)
    equity_curve = db.Column(db.JSON, default=list)
    trades_data = db.Column(db.JSON, default=list)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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
            "sharpe_ratio": self.sharpe_ratio,
            "profit_factor": self.profit_factor,
            "created_at": self.created_at.isoformat(),
        }
