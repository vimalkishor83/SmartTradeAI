from datetime import datetime
from app.extensions import db


class TechnicalIndicator(db.Model):
    __tablename__ = "technical_indicators"

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)

    # Trend
    ema20 = db.Column(db.Float)
    ema50 = db.Column(db.Float)
    ema100 = db.Column(db.Float)
    ema200 = db.Column(db.Float)
    sma20 = db.Column(db.Float)
    sma50 = db.Column(db.Float)
    vwap = db.Column(db.Float)
    supertrend = db.Column(db.Float)
    supertrend_direction = db.Column(db.String(5))  # up/down
    ichimoku_tenkan = db.Column(db.Float)
    ichimoku_kijun = db.Column(db.Float)
    ichimoku_senkou_a = db.Column(db.Float)
    ichimoku_senkou_b = db.Column(db.Float)

    # Momentum
    rsi = db.Column(db.Float)
    macd = db.Column(db.Float)
    macd_signal = db.Column(db.Float)
    macd_hist = db.Column(db.Float)
    stoch_rsi_k = db.Column(db.Float)
    stoch_rsi_d = db.Column(db.Float)
    cci = db.Column(db.Float)
    roc = db.Column(db.Float)

    # Volatility
    atr = db.Column(db.Float)
    bb_upper = db.Column(db.Float)
    bb_middle = db.Column(db.Float)
    bb_lower = db.Column(db.Float)
    bb_width = db.Column(db.Float)
    keltner_upper = db.Column(db.Float)
    keltner_lower = db.Column(db.Float)

    # Volume
    obv = db.Column(db.Float)
    cmf = db.Column(db.Float)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index("idx_indicators_asset_tf_ts", "asset_id", "timeframe", "timestamp"),
    )

    def to_dict(self):
        return {
            "asset_id": self.asset_id,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp.isoformat(),
            "ema20": self.ema20, "ema50": self.ema50, "ema200": self.ema200,
            "rsi": self.rsi, "macd": self.macd, "macd_signal": self.macd_signal,
            "atr": self.atr, "bb_upper": self.bb_upper, "bb_lower": self.bb_lower,
            "vwap": self.vwap, "supertrend": self.supertrend,
            "obv": self.obv, "cmf": self.cmf,
        }
