from datetime import datetime
from app.extensions import db


class Asset(db.Model):
    __tablename__ = "assets"

    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(30), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    market = db.Column(db.String(30), nullable=False)  # crypto, forex, commodity, indian_stock, index
    exchange = db.Column(db.String(50))
    base_currency = db.Column(db.String(10))
    quote_currency = db.Column(db.String(10))
    is_active = db.Column(db.Boolean, default=True)
    data_source = db.Column(db.String(50))  # binance, alphavantage, zerodha, etc.
    pip_size = db.Column(db.Float, default=0.0001)
    lot_size = db.Column(db.Float, default=1.0)
    min_lot = db.Column(db.Float, default=0.01)
    metadata_ = db.Column("metadata", db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    signals = db.relationship("Signal", backref="asset", lazy="dynamic")

    __table_args__ = (db.UniqueConstraint("symbol", "exchange", name="uq_symbol_exchange"),)

    MARKETS = ["crypto", "forex", "gold", "silver", "indian_stock", "index"]

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "name": self.name,
            "market": self.market,
            "exchange": self.exchange,
            "is_active": self.is_active,
            "data_source": self.data_source,
        }

    def __repr__(self):
        return f"<Asset {self.symbol}>"
