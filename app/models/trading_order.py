"""Durable idempotency records and isolated paper orders."""

from datetime import datetime

from app.extensions import db


class TradeRequest(db.Model):
    __tablename__ = "trade_requests"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    idempotency_key = db.Column(db.String(128), nullable=False)
    request_hash = db.Column(db.String(64), nullable=False)
    mode = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    response = db.Column(db.JSON)
    broker_order_id = db.Column(db.String(100))
    requested_exposure = db.Column(db.Numeric(24, 8), nullable=False, default=0)
    requested_open_risk = db.Column(db.Numeric(24, 8), nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("user_id", "idempotency_key", name="uq_trade_request_user_key"),
        db.Index("idx_trade_request_user_created", "user_id", "created_at"),
    )


class PaperOrder(db.Model):
    __tablename__ = "paper_orders"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    client_order_id = db.Column(db.String(128), nullable=False)
    symbol = db.Column(db.String(40), nullable=False)
    side = db.Column(db.String(10), nullable=False)
    order_type = db.Column(db.String(20), nullable=False)
    size = db.Column(db.Integer, nullable=False)
    limit_price = db.Column(db.Numeric(24, 8))
    stop_price = db.Column(db.Numeric(24, 8))
    fill_price = db.Column(db.Numeric(24, 8))
    reduce_only = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(20), nullable=False, default="accepted")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("user_id", "client_order_id", name="uq_paper_order_user_client_id"),
        db.Index("idx_paper_order_user_status", "user_id", "status"),
    )

    def to_dict(self):
        def number(value):
            return float(value) if value is not None else None

        return {
            "id": self.id,
            "client_order_id": self.client_order_id,
            "mode": "paper",
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "size": self.size,
            "limit_price": number(self.limit_price),
            "stop_price": number(self.stop_price),
            "fill_price": number(self.fill_price),
            "reduce_only": bool(self.reduce_only),
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
