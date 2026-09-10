from datetime import datetime

from app.extensions import db


class BacktestSweep(db.Model):
    """A persisted, multi-dimensional strategy comparison run.

    The result payload is intentionally self-contained so the report remains
    reviewable after temporary market-data frames have been released.
    """

    __tablename__ = "backtest_sweeps"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    assets = db.Column(db.JSON, nullable=False, default=list)
    strategies = db.Column(db.JSON, nullable=False, default=list)
    timeframes = db.Column(db.JSON, nullable=False, default=list)
    candle_limit = db.Column(db.Integer, nullable=False, default=400)
    initial_capital = db.Column(db.Float, nullable=False, default=100000)
    commission = db.Column(db.Float, nullable=False, default=0.001)
    slippage = db.Column(db.Float, nullable=False, default=0.0005)
    spread = db.Column(db.Float, nullable=False, default=0.0)
    total_cells = db.Column(db.Integer, nullable=False, default=0)
    completed_cells = db.Column(db.Integer, nullable=False, default=0)
    result_data = db.Column(db.JSON, nullable=False, default=dict)
    summary = db.Column(db.JSON, nullable=False, default=dict)
    errors = db.Column(db.JSON, nullable=False, default=list)
    engine_version = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    user = db.relationship("User")

    def to_dict(self, include_results=False):
        data = {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "assets": self.assets or [],
            "strategies": self.strategies or [],
            "timeframes": self.timeframes or [],
            "candle_limit": self.candle_limit,
            "initial_capital": self.initial_capital,
            "commission": self.commission,
            "slippage": self.slippage,
            "spread": self.spread,
            "total_cells": self.total_cells,
            "completed_cells": self.completed_cells,
            "summary": self.summary or {},
            "errors": self.errors or [],
            "engine_version": self.engine_version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
        if include_results:
            data["result_data"] = self.result_data or {"cells": []}
        return data
