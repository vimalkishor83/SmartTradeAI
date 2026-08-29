from datetime import datetime
from app.extensions import db


class SavedScreen(db.Model):
    """A user's named Delta Market Screener filter (asset type + WHERE
    conditions + AND/OR combinator), so a filter combination they use
    regularly can be reapplied without rebuilding it every visit — mirrors
    Cryptomaty's "Save screen" / "Saved" dropdown on their Crypto Screener
    page (see project_cryptomaty_scanner_research memory)."""
    __tablename__ = "saved_screens"

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name         = db.Column(db.String(100), nullable=False)
    asset_type   = db.Column(db.String(30), nullable=False, default="perpetual_futures")
    combinator   = db.Column(db.String(3), nullable=False, default="AND")
    conditions   = db.Column(db.JSON, nullable=False, default=list)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "name", name="uq_saved_screen_user_name"),)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "asset_type": self.asset_type,
            "combinator": self.combinator,
            "conditions": self.conditions or [],
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
