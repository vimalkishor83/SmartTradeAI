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
    is_read = db.Column(db.Boolean, default=False)
    is_sent = db.Column(db.Boolean, default=False)
    sent_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "type": self.notification_type,
            "asset": self.asset_symbol,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat(),
        }
