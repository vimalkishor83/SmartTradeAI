from datetime import datetime
from app.extensions import db


class LiveReadLog(db.Model):
    """Tracks Terminal's "live read" cards — the non-persisted analyze()
    fallback market_board() serves when no real Signal exists yet for an
    asset+timeframe (see _frozen_live_read in app/api/v1/signals.py).
    These never went through generate_signal()'s full gate/persistence
    path, so their hypothetical performance was otherwise invisible;
    logging them here lets "did the live-preview board actually call it
    right" be measured the same way real signals are, without mixing them
    into the Signal/SignalHistory tables real trading decisions read from.

    One row per frozen live-read snapshot. `outcome` stays None while the
    hypothetical trade is still open (current price hasn't reached the
    frozen stop-loss or final target yet); _frozen_live_read closes it out
    the moment a fresh read replaces it, using the same win/loss condition
    that would close a real signal.
    """
    __tablename__ = "live_read_logs"

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False, index=True)
    timeframe = db.Column(db.String(10), nullable=False, index=True)
    signal_type = db.Column(db.String(10), nullable=False)  # BUY or SELL
    confidence_score = db.Column(db.Float)
    entry_price = db.Column(db.Float, nullable=False)
    stop_loss = db.Column(db.Float)
    target1 = db.Column(db.Float)
    target2 = db.Column(db.Float)
    target3 = db.Column(db.Float)
    outcome = db.Column(db.String(10))       # None (open), "win", or "loss"
    exit_price = db.Column(db.Float)
    generated_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    resolved_at = db.Column(db.DateTime)

    # Same "why" data a real Signal row carries (see Signal.reasoning /
    # reasoning_detail / regime) — added after the fact because a live
    # read's rationale was otherwise only ever shown live in the Terminal
    # UI at generation time and never actually persisted anywhere, so a
    # closed one couldn't be reviewed afterward to see whether the thesis
    # held up.
    reasoning = db.Column(db.Text)
    reasoning_detail = db.Column(db.JSON, default=list)
    regime = db.Column(db.String(30))

    asset = db.relationship("Asset")

    def to_dict(self):
        return {
            "id": self.id,
            "asset": self.asset.symbol if self.asset else None,
            "timeframe": self.timeframe,
            "signal_type": self.signal_type,
            "confidence_score": self.confidence_score,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "outcome": self.outcome,
            "exit_price": self.exit_price,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "reasoning": self.reasoning,
            "reasoning_detail": self.reasoning_detail,
            "regime": self.regime,
        }
