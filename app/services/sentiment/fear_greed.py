"""
Crypto Fear & Greed Index via alternative.me — free, keyless.

Separate from app/services/sentiment/engine.py, which computes a local
per-asset technical+news sentiment score. This module fetches a single
external market-wide index instead.
"""
from __future__ import annotations
import logging
import requests

logger = logging.getLogger(__name__)

FNG_URL = "https://api.alternative.me/fng/"


def fetch_fear_greed(history_days: int = 14) -> dict:
    """
    Returns the current Crypto Fear & Greed Index value plus a short
    history. Scoped explicitly to crypto — alternative.me's index is
    BTC-market-derived, not a general equity sentiment gauge (no free,
    keyless equivalent for equities was found; CNN's Fear & Greed has no
    public API).
    """
    try:
        resp = requests.get(
            FNG_URL,
            params={"limit": history_days, "format": "json"},
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        logger.warning(f"alternative.me Fear&Greed fetch failed: {e}")
        return {
            "current": None,
            "history": [],
            "scope": "crypto-only",
            "source": "alternative.me",
            "note": "Upstream Fear & Greed API did not respond.",
        }

    entries = payload.get("data") or []
    history = [
        {
            "value": int(e["value"]),
            "classification": e.get("value_classification"),
            "timestamp": int(e["timestamp"]),
        }
        for e in entries if e.get("value") is not None
    ]

    return {
        "current": history[0] if history else None,
        "history": history,
        "scope": "crypto-only",
        "source": "alternative.me",
        "note": "BTC-market-derived index — not a general equity sentiment gauge. No free, keyless equity equivalent exists.",
    }
