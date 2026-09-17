from datetime import datetime
from app.extensions import db


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50))  # new_signal, target_hit, sl_hit, reversal, volatility
    channel = db.Column(db.String(20))  # email, telegram, push, web
    asset_symbol = db.Column(db.String(30))
    signal_id = db.Column(db.Integer, db.ForeignKey("signals.id"))
    # Stable source/event idempotency key for queued lifecycle notifications.
    # Null keeps older notification producers backward compatible.
    notification_key = db.Column(db.String(180), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    is_sent = db.Column(db.Boolean, default=False)
    sent_at = db.Column(db.DateTime)
    # Delivery state is separate from the in-app notification lifecycle. It
    # makes disabled, retrying and permanently failed external deliveries
    # observable without deleting the user's notification row.
    delivery_status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.Text)
    next_attempt_at = db.Column(db.DateTime)
    skipped_reason = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index("idx_notif_user_sent",  "user_id", "is_sent"),
        db.Index("idx_notif_user_read",  "user_id", "is_read"),
        db.Index("idx_notif_created",    "created_at"),
        db.Index("idx_notif_delivery_queue", "is_sent", "created_at", "id"),
        db.Index("idx_notif_delivery_due", "delivery_status", "next_attempt_at", "created_at", "id"),
        db.Index("uq_notif_user_key", "user_id", "notification_key", unique=True),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "type": self.notification_type,
            "asset": self.asset_symbol,
            "is_read": self.is_read,
            "delivery_status": self.delivery_status or ("sent" if self.is_sent else "pending"),
            "attempt_count": self.attempt_count or 0,
            "skipped_reason": self.skipped_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
