from flask import Blueprint, request, jsonify
from app.models.news import News
from app.models.economic import EconomicEvent
from app.auth.decorators import login_required
from app.extensions import cache

news_bp = Blueprint("news", __name__)


@news_bp.route("/", methods=["GET"])
@login_required
def get_news():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    sentiment = request.args.get("sentiment")

    query = News.query
    if sentiment:
        query = query.filter_by(sentiment=sentiment)

    news = query.order_by(News.published_at.desc()) \
        .paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "news": [n.to_dict() for n in news.items],
        "total": news.total,
        "pages": news.pages,
    }), 200


@news_bp.route("/economic-calendar", methods=["GET"])
@login_required
@cache.cached(timeout=3600, key_prefix="econ_calendar")
def economic_calendar():
    from datetime import datetime, timedelta
    start = datetime.utcnow()
    end = start + timedelta(days=7)
    events = EconomicEvent.query.filter(
        EconomicEvent.event_time.between(start, end)
    ).order_by(EconomicEvent.event_time).all()
    return jsonify({"events": [e.to_dict() for e in events]}), 200
