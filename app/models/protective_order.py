from datetime import datetime
from app.extensions import db


class ProtectiveOrder(db.Model):
    """A user-configured stop-loss / take-profit / trailing-stop watch on
    one of their PortfolioItem holdings.

    This does NOT represent a broker-native order sitting on the exchange
    (Delta's own stop_price param on place_order() covers that case at
    entry time) -- it represents the app's own background monitor for a
    position the user already holds, which polls live price and reacts
    when a level is breached. Two modes:
      - auto_execute=False (default): monitor + notify only. The user gets
        an alert and closes the position themselves.
      - auto_execute=True: on breach, the monitor places a real
        reduce_only market order via the user's connected Delta client to
        close the position, then marks this row "executed".
    is_dry_run additionally gates the auto_execute path: while True, a
    breach still logs/notifies exactly as if the order were sent, but the
    actual place_order() call is skipped -- lets a user validate their
    trailing-stop distance/behavior against real price action before
    trusting it with real order submission.
    """
    __tablename__ = "protective_orders"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    portfolio_item_id = db.Column(db.Integer, db.ForeignKey("portfolio_items.id"), nullable=False, index=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)

    # Static levels (either/both may be set)
    stop_loss = db.Column(db.Float)
    take_profit = db.Column(db.Float)

    # Trailing-stop config
    trailing_enabled = db.Column(db.Boolean, default=False, nullable=False)
    trailing_distance_pct = db.Column(db.Float)   # e.g. 2.0 = trail 2% behind the high-water mark
    high_water_mark = db.Column(db.Float)          # best price seen since this row was created/reset

    # Execution mode -- BOTH default to the safe/off state
    auto_execute = db.Column(db.Boolean, default=False, nullable=False)
    is_dry_run = db.Column(db.Boolean, default=True, nullable=False)

    # side: "long" or "short" -- determines breach direction (SL below
    # entry for long, above entry for short) and trailing direction
    side = db.Column(db.String(10), nullable=False, default="long")

    status = db.Column(db.String(20), nullable=False, default="active")
    # active | triggered_sl | triggered_tp | triggered_trailing | cancelled | error

    last_checked_price = db.Column(db.Float)
    last_checked_at = db.Column(db.DateTime)
    triggered_at = db.Column(db.DateTime)
    trigger_price = db.Column(db.Float)
    broker_order_result = db.Column(db.Text)   # JSON string of the place_order() response, if executed
    error_message = db.Column(db.String(500))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    portfolio_item = db.relationship("PortfolioItem")
    asset = db.relationship("Asset")

    __table_args__ = (
        db.Index("idx_protective_order_status", "status"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "portfolio_item_id": self.portfolio_item_id,
            "asset": self.asset.symbol if self.asset else None,
            "side": self.side,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "trailing_enabled": self.trailing_enabled,
            "trailing_distance_pct": self.trailing_distance_pct,
            "high_water_mark": self.high_water_mark,
            "auto_execute": self.auto_execute,
            "is_dry_run": self.is_dry_run,
            "status": self.status,
            "last_checked_price": self.last_checked_price,
            "last_checked_at": self.last_checked_at.isoformat() if self.last_checked_at else None,
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
            "trigger_price": self.trigger_price,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
        }
