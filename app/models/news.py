from datetime import datetime
from app.extensions import db


class News(db.Model):
    __tablename__ = "news"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    summary = db.Column(db.Text)
    url = db.Column(db.String(1000))
    source = db.Column(db.String(100))
    image_url = db.Column(db.String(1000))
    sentiment = db.Column(db.String(20))  # positive, negative, neutral
    sentiment_score = db.Column(db.Float)
    related_assets = db.Column(db.JSON, default=list)
    published_at = db.Column(db.DateTime)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "source": self.source,
            "sentiment": self.sentiment,
            "related_assets": self.related_assets,
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }
