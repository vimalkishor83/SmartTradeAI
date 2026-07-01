from datetime import datetime
from app.extensions import db
from sqlalchemy.orm import relationship


class Signal(db.Model):
    __tablename__ = "signals"

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)
    signal_type = db.Column(db.String(10), nullable=False)  # BUY, SELL, HOLD, EXIT
    entry_price = db.Column(db.Float)
    stop_loss = db.Column(db.Float)
    target1 = db.Column(db.Float)
    target2 = db.Column(db.Float)
    target3 = db.Column(db.Float)
    risk_reward = db.Column(db.Float)
    confidence_score = db.Column(db.Float, default=0)
    confidence_label = db.Column(db.String(20))  # Very Strong, Strong, Moderate, Weak

    # Score breakdown
    trend_score = db.Column(db.Float, default=0)
    momentum_score = db.Column(db.Float, default=0)
    volume_score = db.Column(db.Float, default=0)
    pattern_score = db.Column(db.Float, default=0)
    ai_score = db.Column(db.Float, default=0)

    # Status
    status = db.Column(db.String(20), default="active")  # active, expired, hit_target, hit_sl
    current_price = db.Column(db.Float)
    pnl_pct = db.Column(db.Float, default=0)

    # Indicators snapshot
    indicators = db.Column(db.JSON, default=dict)
    patterns = db.Column(db.JSON, default=list)
    reasoning = db.Column(db.Text)

    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index("idx_signals_asset_tf",       "asset_id", "timeframe"),
        db.Index("idx_signals_status_time",    "status",   "generated_at"),
        db.Index("idx_signals_asset_tf_time",  "asset_id", "timeframe", "generated_at"),
    )

    SIGNAL_TYPES = ["BUY", "SELL", "HOLD", "EXIT"]
    CONFIDENCE_LABELS = {
        (90, 100): "Very Strong",
        (75, 89): "Strong",
        (60, 74): "Moderate",
        (0, 59): "Weak",
    }

    def set_confidence_label(self):
        score = self.confidence_score or 0
        if score >= 90:
            self.confidence_label = "Very Strong"
        elif score >= 75:
            self.confidence_label = "Strong"
        elif score >= 60:
            self.confidence_label = "Moderate"
        else:
            self.confidence_label = "Weak"

    def to_dict(self):
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "asset": self.asset.symbol if self.asset else None,
            "market": self.asset.market if self.asset else None,
            "timeframe": self.timeframe,
            "signal_type": self.signal_type,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "target1": self.target1,
            "target2": self.target2,
            "target3": self.target3,
            "risk_reward": self.risk_reward,
            "confidence_score": self.confidence_score,
            "confidence_label": self.confidence_label,
            "trend_score":      self.trend_score,
            "momentum_score":   self.momentum_score,
            "volume_score":     self.volume_score,
            "pattern_score":    self.pattern_score,
            "ai_score":         self.ai_score,
            "status": self.status,
            "current_price": self.current_price,
            "pnl_pct": self.pnl_pct,
            "patterns": self.patterns,
            "reasoning": self.reasoning,
            "generated_at": self.generated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


class SignalHistory(db.Model):
    __tablename__ = "signal_history"

    id = db.Column(db.Integer, primary_key=True)
    signal_id = db.Column(db.Integer, db.ForeignKey("signals.id"))
    asset_id  = db.Column(db.Integer, db.ForeignKey("assets.id"))
    asset     = relationship("Asset", lazy="select")
    timeframe = db.Column(db.String(10))
    signal_type = db.Column(db.String(10))
    entry_price = db.Column(db.Float)
    exit_price = db.Column(db.Float)
    stop_loss = db.Column(db.Float)
    target1 = db.Column(db.Float)
    confidence_score = db.Column(db.Float)
    outcome = db.Column(db.String(20))  # win, loss, neutral
    pnl_pct = db.Column(db.Float)
    duration_minutes = db.Column(db.Integer)
    generated_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index("idx_sh_asset_outcome",  "asset_id", "outcome"),
        db.Index("idx_sh_closed_at",      "closed_at"),
        db.Index("idx_sh_timeframe_out",  "timeframe", "outcome"),
    )
