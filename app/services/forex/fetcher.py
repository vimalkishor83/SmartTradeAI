"""
Forex currency-strength matrix using Frankfurter.app — free, keyless,
ECB-sourced daily reference rates.
"""
from __future__ import annotations
import logging
from datetime import date, timedelta
import requests

logger = logging.getLogger(__name__)

FRANKFURTER_URL = "https://api.frankfurter.dev/v1"

MAJOR_CURRENCIES = ["EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "CNY", "INR", "NZD"]
LOOKBACK_DAYS = 7


def _fetch_rates(base: str, as_of: str | None = None) -> dict | None:
    url = f"{FRANKFURTER_URL}/{as_of or 'latest'}"
    try:
        resp = requests.get(url, params={"base": base}, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Frankfurter fetch failed ({url}, base={base}): {e}")
        return None


def fetch_forex_strength() -> dict:
    """
    Returns USD-vs-major-currency rates plus a 7-day % change per currency,
    used as a simple strength/weakness read. Returns pairs=[] on total
    failure rather than raising.
    """
    latest = _fetch_rates("USD")
    if latest is None:
        return {
            "pairs": [],
            "as_of": None,
            "source": "Frankfurter.app (ECB rates)",
            "note": "Upstream Frankfurter API did not respond.",
        }

    lookback_date = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    historical = _fetch_rates("USD", lookback_date)
    hist_rates = (historical or {}).get("rates", {})

    pairs = []
    for ccy in MAJOR_CURRENCIES:
        current = latest.get("rates", {}).get(ccy)
        if current is None:
            continue
        past = hist_rates.get(ccy)
        change_pct = None
        if past:
            # Rates are USD -> ccy; a RISING rate means the foreign
            # currency WEAKENED against USD (takes more of it per USD).
            change_pct = round((current - past) / past * 100, 3)
        pairs.append({
            "pair": f"USD/{ccy}",
            "rate": current,
            "change_pct_7d": change_pct,
            # Negative change_pct_7d = currency strengthened vs USD.
            "strength": None if change_pct is None else ("strengthening" if change_pct < 0 else "weakening"),
        })

    return {
        "pairs": pairs,
        "as_of": latest.get("date"),
        "compared_to": lookback_date if hist_rates else None,
        "source": "Frankfurter.app (ECB rates)",
        "note": "ECB daily reference rates — one update per weekday, not intraday.",
    }
