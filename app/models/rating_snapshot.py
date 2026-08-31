from datetime import datetime
from app.extensions import db


class RatingSnapshot(db.Model):
    """Last-known EMA 9/21 MTF rating per (asset, timeframe) — the only way
    to detect a *change* (Sell -> Buy -> Strong Buy, etc.) is to remember
    what it was on the previous prewarm cycle and compare. One row per
    (asset_id, timeframe); prewarm_ta_cache upserts this every 5 minutes
    right after computing the fresh rating, so the compare-and-alert step
    always runs against the immediately preceding cycle, never a stale one."""
    __tablename__ = "rating_snapshots"

    id         = db.Column(db.Integer, primary_key=True)
    asset_id   = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False, index=True)
    timeframe  = db.Column(db.String(10), nullable=False)
    rating     = db.Column(db.String(20), nullable=False)  # Strong Buy / Buy / Neutral / Sell / Strong Sell
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("asset_id", "timeframe", name="uq_rating_snapshot_asset_tf"),
    )
