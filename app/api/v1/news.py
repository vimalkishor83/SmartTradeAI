from flask import Blueprint, request, jsonify, current_app
import threading
from app.models.news import News
from app.models.economic import EconomicEvent
from app.extensions import cache
from app.services.pagination import bounded_page, bounded_per_page
import logging

logger = logging.getLogger(__name__)
news_bp = Blueprint("news", __name__)

_NEWS_FETCH_MARKER = "news_fetch_in_progress"
_NEWS_FETCH_MARKER_TTL = 60
_ECONOMIC_CALENDAR_FETCH_LOCK = threading.Lock()


@news_bp.route("/", methods=["GET"])
def get_news():
    """Public/no-auth: read-only news feed, matches the reference site's
    free "Desk Notes" dashboard tier."""
    page = bounded_page(request.args.get("page", 1))
    per_page = bounded_per_page(request.args.get("per_page", 20))
    sentiment = request.args.get("sentiment")
    market = request.args.get("market")

    query = News.query
    if sentiment:
        query = query.filter_by(sentiment=sentiment)

    total = query.count()

    if total == 0:
        # No news yet — trigger a background fetch and tell the client to retry
        try:
            # A refresh burst must not spawn one provider job per request.
            # The marker is deliberately short-lived so a failed worker cannot
            # suppress retries forever; a successful worker makes this branch
            # unnecessary as soon as rows are committed.
            if not cache.get(_NEWS_FETCH_MARKER):
                cache.set(_NEWS_FETCH_MARKER, "1", timeout=_NEWS_FETCH_MARKER_TTL)
                from app.tasks.data_tasks import fetch_news
                t = threading.Thread(
                    target=fetch_news,
                    args=[current_app._get_current_object()],
                    daemon=True,
                )
                t.start()
        except Exception as e:
            cache.delete(_NEWS_FETCH_MARKER)
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
def economic_calendar():
    """Public/no-auth: read-only calendar, matches the reference site's
    free "Economic Calendar" dashboard tier."""
    from datetime import datetime, timedelta

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
        # Several pages request this endpoint at startup. Only the first cold
        # request should contact Forex Factory; later requests re-check cache
        # and DB after waiting for that refresh to finish.
        with _ECONOMIC_CALENDAR_FETCH_LOCK:
            cached = cache.get("econ_calendar")
            if cached:
                return jsonify(cached), 200
            events = _calendar_events_between(start, end)
            if not events:
                events = _fetch_economic_calendar(start, end)

    result = {"events": [e.to_dict() for e in events]}
    cache.set("econ_calendar", result, timeout=3600)
    return jsonify(result), 200


def _calendar_events_between(start, end):
    return (EconomicEvent.query
            .filter(EconomicEvent.event_time.between(start, end))
            .order_by(EconomicEvent.event_time)
            .all())


def _fetch_economic_calendar(start, end):
    """Fetch, batch-upsert, and return the current Forex Factory window."""
    import requests as req
    from datetime import datetime, timezone
    from app.extensions import db

    urls = [
        "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
    ]
    all_raw = []
    for url in urls:
        try:
            resp = req.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            all_raw.extend(resp.json())
        except Exception as e:
            logger.debug(f"Economic calendar fetch failed: {e}")

    # Parse first so existing rows can be fetched with one ranged query.
    parsed = []
    for ev in all_raw:
        title = ev.get("title", "").strip()
        date_str = ev.get("date", "")
        if not title or not date_str:
            continue
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
        parsed.append({
            "title": title, "event_time": event_time, "impact": impact,
            "country": ev.get("country", ""), "forecast": ev.get("forecast"),
            "previous": ev.get("previous"), "actual": ev.get("actual"),
        })

    if parsed:
        times = [p["event_time"] for p in parsed]
        existing_rows = (EconomicEvent.query
                         .filter(EconomicEvent.event_time.between(min(times), max(times)))
                         .all())
        existing_by_key = {(e.title, e.event_time): e for e in existing_rows}

        for p in parsed:
            key = (p["title"], p["event_time"])
            existing = existing_by_key.get(key)
            if existing:
                existing.actual = p["actual"] or existing.actual
            else:
                event = EconomicEvent(
                    title=p["title"],
                    country=p["country"],
                    currency=p["country"],
                    impact=p["impact"],
                    forecast=p["forecast"],
                    previous=p["previous"],
                    actual=p["actual"],
                    event_time=p["event_time"],
                )
                db.session.add(event)
                # Both weekly feeds can contain the same event.
                existing_by_key[key] = event
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Economic calendar DB save failed: {e}")

    return _calendar_events_between(start, end)
