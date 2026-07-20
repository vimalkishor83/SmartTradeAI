from datetime import datetime
from app.extensions import db


class JournalEntry(db.Model):
    __tablename__ = "journal_entries"
    # Every journal endpoint (list/stats/tax-report) filters by user_id, and
    # tax-report additionally orders by trade_date — a composite index serves
    # both the filter and the sort without a table scan.
    __table_args__ = (
        db.Index("idx_journal_user_trade_date", "user_id", "trade_date"),
    )
    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    asset_id       = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=True)
    trade_date     = db.Column(db.Date, nullable=False)
    market         = db.Column(db.String(30))           # crypto, forex, etc.
    direction      = db.Column(db.String(10))            # BUY / SELL
    timeframe      = db.Column(db.String(10))
    entry_price    = db.Column(db.Float)
    exit_price     = db.Column(db.Float)
    quantity       = db.Column(db.Float)
    stop_loss      = db.Column(db.Float)
    target         = db.Column(db.Float)
    outcome        = db.Column(db.String(10))            # win / loss / breakeven
    pnl_amount     = db.Column(db.Float)                 # absolute P&L in ₹
    pnl_pct        = db.Column(db.Float)
    emotion_tag    = db.Column(db.String(30))            # disciplined / fomo / revenge / patient / anxious
    setup_tags     = db.Column(db.JSON, default=list)    # ["breakout","ema_cross","rsi_oversold"]
    notes          = db.Column(db.Text)
    screenshot_url = db.Column(db.String(500))
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at     = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    asset = db.relationship("Asset", lazy="joined")

    def to_dict(self):
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "asset_symbol": self.asset.symbol if self.asset else None,
            "trade_date": self.trade_date.isoformat() if self.trade_date else None,
            "market": self.market,
            "direction": self.direction,
            "timeframe": self.timeframe,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "stop_loss": self.stop_loss,
            "target": self.target,
            "outcome": self.outcome,
            "pnl_amount": self.pnl_amount,
            "pnl_pct": self.pnl_pct,
            "emotion_tag": self.emotion_tag,
            "setup_tags": self.setup_tags or [],
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
        }
