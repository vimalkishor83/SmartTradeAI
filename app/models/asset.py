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

    # Was ["crypto", "forex", "gold", "silver", "indian_stock", "index"] --
    # stale against reality on two counts, found during a codebase audit:
    # every real asset uses market="commodity" (not "gold"/"silver"
    # separately, which no asset actually has), and "us_stock" was missing
    # even though APIConfig.PROVIDERS["us_stock"] and the broker registry
    # (Alpaca, Interactive Brokers, Tradier, TD Ameritrade) already exist
    # for it. No live page currently calls POST /assets/ directly (this
    # list is otherwise only enforced there and on PUT), so this had zero
    # live-user impact, but it would have silently rejected a real
    # "commodity" asset the moment anything did.
    MARKETS = ["crypto", "forex", "commodity", "indian_stock", "us_stock", "index"]

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
