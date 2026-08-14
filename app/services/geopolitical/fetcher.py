"""
Geopolitical risk signal using the GDELT DOC 2.0 API — free, keyless.

GDELT enforces an informal ~1 request/5s throttle per IP (undocumented
exact limit, observed in practice to be stricter). We only ever issue ONE
query per fetch (not one per topic) to stay well clear of it — the route
layer caches the result for 15 minutes, so this function is called at most
a few times per hour regardless of user traffic.
"""
from __future__ import annotations
import logging
import requests
from collections import Counter

logger = logging.getLogger(__name__)

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Single combined query covering major geopolitical risk themes —
# one GDELT call, not one per theme, to respect the rate limit.
RISK_QUERY = (
    '(war OR conflict OR sanctions OR "military strike" OR invasion OR '
    'coup OR "trade war") sourcelang:english'
)


def fetch_geopolitical_risk() -> dict:
    """
    Returns a dict with a 0-100 risk score derived from recent (24h)
    article volume and country spread on conflict/crisis-themed coverage,
    plus the underlying headlines. Returns risk_score=None on failure
    rather than raising — this is a best-effort signal from a free,
    unauthenticated, no-SLA public API.
    """
    try:
        resp = requests.get(
            GDELT_URL,
            params={
                "query": RISK_QUERY,
                "mode": "artlist",
                "format": "json",
                "timespan": "24h",
                "maxrecords": "75",
                "sort": "hybridrel",
            },
            timeout=25,  # GDELT is slow (observed 10-20s), not just rate-limited
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        logger.warning(f"GDELT fetch failed: {e}")
        return {
            "risk_score": None,
            "risk_label": "unavailable",
            "article_count": 0,
            "top_countries": [],
            "headlines": [],
            "source": "GDELT DOC 2.0",
            "note": "Upstream GDELT API did not respond — no live-market fallback exists for this signal.",
        }

    articles = payload.get("articles") or []
    article_count = len(articles)

    countries = Counter(a.get("sourcecountry") for a in articles if a.get("sourcecountry"))
    top_countries = [{"country": c, "count": n} for c, n in countries.most_common(8)]

    # Simple, transparent volume-based proxy: more crisis-themed coverage
    # from more distinct countries in a 24h window => higher score.
    # Not a calibrated academic index — labeled as a proxy, not a "true" score.
    distinct_countries = len(countries)
    raw = min(article_count, 75) * 0.8 + min(distinct_countries, 25) * 1.6
    risk_score = round(min(100, raw), 1)

    if risk_score >= 70:
        label = "elevated"
    elif risk_score >= 40:
        label = "moderate"
    else:
        label = "low"

    headlines = [
        {
            "title": a.get("title"),
            "url": a.get("url"),
            "domain": a.get("domain"),
            "country": a.get("sourcecountry"),
            "seen_at": a.get("seendate"),
        }
        for a in articles[:12]
    ]

    return {
        "risk_score": risk_score,
        "risk_label": label,
        "article_count": article_count,
        "top_countries": top_countries,
        "headlines": headlines,
        "source": "GDELT DOC 2.0",
        "note": "Volume/spread-based proxy over 24h of conflict/crisis-themed coverage — not a calibrated risk index.",
    }
