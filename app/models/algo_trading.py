"""Per-user guardrails for Delta Exchange India algo execution."""
from datetime import datetime

from app.extensions import db


DEFAULT_ORDER_RULES = {
    "buy_entry": {"order_type": "limit_order", "time_in_force": "gtc"},
    "sell_entry": {"order_type": "limit_order", "time_in_force": "gtc"},
    "long_stop_loss": {"order_type": "market_order", "time_in_force": None},
    "short_stop_loss": {"order_type": "market_order", "time_in_force": None},
    "long_take_profit": {"order_type": "limit_order", "time_in_force": "gtc"},
    "short_take_profit": {"order_type": "limit_order", "time_in_force": "gtc"},
}


class AlgoExecutionPolicy(db.Model):
    __tablename__ = "algo_execution_policies"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True, index=True)
    execution_provider = db.Column(db.String(40), nullable=False, default="delta_exchange_india")
    mode = db.Column(db.String(10), nullable=False, default="paper")
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    max_margin_amount = db.Column(db.Numeric(20, 8), nullable=False, default=0)
    max_notional_amount = db.Column(db.Numeric(20, 8), nullable=False, default=0)
    max_leverage = db.Column(db.Integer, nullable=False, default=1)
    max_open_positions = db.Column(db.Integer, nullable=False, default=1)
    max_daily_loss = db.Column(db.Numeric(20, 8), nullable=False, default=0)
    max_slippage_bps = db.Column(db.Numeric(10, 4), nullable=False, default=50)
    order_rules = db.Column(db.JSON, nullable=False, default=lambda: dict(DEFAULT_ORDER_RULES))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        def number(value):
            return float(value or 0)

        rules = self.order_rules or DEFAULT_ORDER_RULES
        return {
            "id": self.id,
            "user_id": self.user_id,
            "execution_provider": self.execution_provider,
            "mode": self.mode,
            "enabled": bool(self.enabled),
            "max_margin_amount": number(self.max_margin_amount),
            "max_notional_amount": number(self.max_notional_amount),
            "max_leverage": self.max_leverage,
            "max_open_positions": self.max_open_positions,
            "max_daily_loss": number(self.max_daily_loss),
            "max_slippage_bps": number(self.max_slippage_bps),
            "order_rules": rules,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
