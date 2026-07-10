from flask import Blueprint, request, jsonify, current_app
from app.models.news import News
from app.models.economic import EconomicEvent
from app.auth.decorators import login_required
from app.extensions import cache
import logging

logger = logging.getLogger(__name__)
news_bp = Blueprint("news", __name__)


@news_bp.route("/", methods=["GET"])
@login_required
def get_news():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    sentiment = request.args.get("sentiment")
    market = request.args.get("market")

    query = News.query
    if sentiment:
        query = query.filter_by(sentiment=sentiment)

    total = query.count()

    if total == 0:
        # No news yet — trigger a background fetch and tell the client to retry
        try:
            from app.tasks.data_tasks import fetch_news
            import threading
            t = threading.Thread(target=fetch_news, args=[current_app._get_current_object()], daemon=True)
            t.start()
        except Exception as e:
            logger.warning(f"Background news fetch trigger failed: {e}")
        return jsonify({"news": [], "total": 0, "pages": 0, "fetching": True}), 200

    news = query.order_by(News.published_at.desc()) \
        .paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "news": [n.to_dict() for n in news.items],
        "total": news.total,
        "pages": news.pages,
        "fetching": False,
    }), 200


@news_bp.route("/economic-calendar", methods=["GET"])
@login_required
def economic_calendar():
    import requests as req
    from datetime import datetime, timedelta, timezone

    # Try cache first
    cached = cache.get("econ_calendar")
    if cached:
        return jsonify(cached), 200

    # Check DB
    now = datetime.utcnow()
    start = now - timedelta(days=1)
    end = now + timedelta(days=14)
    events = EconomicEvent.query.filter(
        EconomicEvent.event_time.between(start, end)
    ).order_by(EconomicEvent.event_time).all()

    if not events:
        # Fetch live from Forex Factory free API
        urls = [
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
        ]
        from app.extensions import db
        all_raw = []
        for url in urls:
            try:
                resp = req.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                all_raw.extend(resp.json())
            except Exception as e:
                logger.debug(f"Economic calendar fetch failed: {e}")

        saved_events = []
        for ev in all_raw:
            title = ev.get("title", "").strip()
            date_str = ev.get("date", "")
            if not title or not date_str:
                continue
            # Forex Factory sends the event's own timezone offset (US Eastern) —
            # it must be converted to UTC, not discarded, or events land 4-5
            # hours early. Naive datetimes are UTC everywhere else in this app.
            event_time = None
            for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
                try:
                    dt = datetime.strptime(date_str, fmt)
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                    event_time = dt
                    break
                except ValueError:
                    continue
            if not event_time:
                continue

            impact_raw = (ev.get("impact") or "").lower()
            impact = impact_raw if impact_raw in ("high", "medium", "low") else "low"
            country = ev.get("country", "")

            existing = EconomicEvent.query.filter_by(title=title, event_time=event_time).first()
            if existing:
                existing.actual = ev.get("actual") or existing.actual
                saved_events.append(existing)
            else:
                event = EconomicEvent(
                    title=title,
                    country=country,
                    currency=country,
                    impact=impact,
                    forecast=ev.get("forecast"),
                    previous=ev.get("previous"),
                    actual=ev.get("actual"),
                    event_time=event_time,
                )
                db.session.add(event)
                saved_events.append(event)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Economic calendar DB save failed: {e}")

        # Re-query after save
        events = EconomicEvent.query.filter(
            EconomicEvent.event_time.between(start, end)
        ).order_by(EconomicEvent.event_time).all()

    result = {"events": [e.to_dict() for e in events]}
    cache.set("econ_calendar", result, timeout=3600)
    return jsonify(result), 200
