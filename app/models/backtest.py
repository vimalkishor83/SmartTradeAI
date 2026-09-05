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

    # Reproducibility provenance. Nullable so historical rows remain readable
    # and clearly show which results predate provenance capture.
    engine_version = db.Column(db.String(50))
    model_version = db.Column(db.String(50))
    config_fingerprint = db.Column(db.String(64))
    data_fingerprint = db.Column(db.String(64))
    data_candles = db.Column(db.Integer)

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
            # winning_trades/losing_trades are cheap scalars, safe to always
            # include. equity_curve/trades_data are NOT included here on
            # purpose — list_backtests() (up to 50 rows) calls this same
            # to_dict(), and each history row would otherwise carry a full
            # ~500-point equity curve + ~100-trade array it never displays.
            # Those two heavy fields are bolted onto the response only where
            # a caller actually shows chart/trade detail for ONE backtest —
            # see get_backtest() below (pre-existing pattern) and
            # POST /backtesting/run (fixed alongside this).
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "net_profit": self.net_profit,
            "net_profit_pct": self.net_profit_pct,
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
            "reproducibility": {
                "backtest_id": self.id,
                "engine_version": self.engine_version,
                "model_version": self.model_version,
                "config_fingerprint": self.config_fingerprint,
                "data_fingerprint": self.data_fingerprint,
                "data_candles": self.data_candles,
                "data_start": self.start_date.isoformat() if self.start_date else None,
                "data_end": self.end_date.isoformat() if self.end_date else None,
            },
            "created_at":      self.created_at.isoformat(),
        }
