from datetime import datetime
from app.extensions import db


class MarketData(db.Model):
    __tablename__ = "market_data"

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)  # 1m, 5m, 15m, 30m, 1h, 4h, 1d
    open = db.Column(db.Float, nullable=False)
    high = db.Column(db.Float, nullable=False)
    low = db.Column(db.Float, nullable=False)
    close = db.Column(db.Float, nullable=False)
    volume = db.Column(db.Float, default=0)
    timestamp = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index("idx_market_data_asset_tf_ts", "asset_id", "timeframe", "timestamp"),
        db.UniqueConstraint("asset_id", "timeframe", "timestamp", name="uq_asset_tf_ts"),
    )

    def to_dict(self):
        return {
            "asset_id": self.asset_id,
            "timeframe": self.timeframe,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "timestamp": self.timestamp.isoformat(),
        }
