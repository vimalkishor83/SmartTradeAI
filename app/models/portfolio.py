from datetime import datetime
from app.extensions import db


class Portfolio(db.Model):
    __tablename__ = "portfolios"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False, default="My Portfolio")
    capital = db.Column(db.Float, default=0)
    currency = db.Column(db.String(10), default="INR")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = db.relationship("PortfolioItem", backref="portfolio", lazy="dynamic", cascade="all, delete-orphan")

    @property
    def total_value(self):
        return sum(item.current_value for item in self.items if item.current_value)

    @property
    def total_pnl(self):
        return sum(item.pnl for item in self.items if item.pnl)


class PortfolioItem(db.Model):
    __tablename__ = "portfolio_items"

    id = db.Column(db.Integer, primary_key=True)
    portfolio_id = db.Column(db.Integer, db.ForeignKey("portfolios.id"), nullable=False)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    buy_price = db.Column(db.Float, nullable=False)
    current_price = db.Column(db.Float)
    stop_loss = db.Column(db.Float)
    target = db.Column(db.Float)
    buy_date = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.String(255))
    # Previously had no timestamp at all besides buy_date (the position's
    # own entry date, not a row-modification audit trail) — made it
    # impossible to tell when a position's stop/target/notes were last edited.
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    asset = db.relationship("Asset")

    @property
    def current_value(self):
        return (self.current_price or self.buy_price) * self.quantity

    @property
    def invested_value(self):
        return self.buy_price * self.quantity

    @property
    def pnl(self):
        return self.current_value - self.invested_value

    @property
    def pnl_pct(self):
        if self.invested_value:
            return (self.pnl / self.invested_value) * 100
        return 0

    @property
    def holding_days(self):
        return (datetime.utcnow() - self.buy_date).days

    def to_dict(self):
        return {
            "id": self.id,
            "asset": self.asset.symbol if self.asset else None,
            "quantity": self.quantity,
            "buy_price": self.buy_price,
            "current_price": self.current_price,
            "current_value": self.current_value,
            "pnl": self.pnl,
            "pnl_pct": round(self.pnl_pct, 2),
            "holding_days": self.holding_days,
        }
