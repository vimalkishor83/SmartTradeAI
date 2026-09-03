"""Dhan (DhanHQ) data fetcher — Indices and Options only, for now.

Deliberately a standalone module: it is NOT wired into market_fetcher's
existing fetch()/fetch_ticker() dispatch, so nothing already running
(crypto via Delta/Binance, Indian stocks/indices via Yahoo) is touched by
this file existing. It's consumed only by the new, isolated
app/api/v1/dhan.py blueprint until someone deliberately decides to route
existing index data through Dhan instead of Yahoo.

Auth: DhanHQ v2 uses a client-id + a long-lived access-token generated
from the Dhan web dashboard (Profile > DhanHQ Trading APIs), sent as
request headers — not the classic API-key/secret OAuth flow. Mapped onto
the existing generic APIConfig row (provider="dhan") as:
    api_key    -> Dhan client_id
    api_secret -> Dhan access_token
No credentials are hardcoded anywhere in this file; until an admin saves
a "dhan" APIConfig row, every method here returns None/empty and logs
why, rather than raising.

IMPORTANT — verify before relying on this: endpoint paths, payload shapes,
and the security IDs below reflect DhanHQ's v2 API as documented at the
time this was written. Confirm against https://dhanhq.co/docs/v2/ once
real credentials are available, since broker APIs do change. The INDEX_
SECURITY_IDS map in particular (NIFTY 50 / NIFTY BANK / SENSEX) should be
cross-checked against Dhan's own published scrip master — get it wrong
and a quote call will simply come back empty rather than obviously
failing.
"""
import logging
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dhan.co/v2"

# Well-known index security IDs on Dhan's IDX_I (index) segment. Confirm
# against Dhan's scrip master (https://images.dhan.co/api-data/api-scrip-master.csv)
# before trusting these for anything beyond an initial smoke test.
INDEX_SECURITY_IDS = {
    "NIFTY 50":     {"security_id": "13", "segment": "IDX_I"},
    "NIFTY BANK":   {"security_id": "25", "segment": "IDX_I"},
    "SENSEX":       {"security_id": "51", "segment": "IDX_I"},
}


def _get_config():
    """The active Dhan APIConfig row, or None if not configured yet."""
    from app.models.api_config import APIConfig
    return APIConfig.query.filter_by(provider="dhan", is_active=True).first()


def _headers(cfg):
    return {
        "access-token": cfg.get_api_secret() or "",
        "client-id": cfg.get_api_key() or "",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def is_configured() -> bool:
    cfg = _get_config()
    return bool(cfg and cfg.get_api_key() and cfg.get_api_secret())


def fetch_index_quotes(names: list[str] | None = None) -> dict:
    """LTP/quote for one or more indices by name (keys of INDEX_SECURITY_IDS).
    Returns {} (not None) when unconfigured or on any error — callers should
    treat an empty dict as "no data available right now", same as every
    other fetcher in this app degrades on failure.
    """
    cfg = _get_config()
    if not cfg:
        logger.info("Dhan fetch skipped: no active 'dhan' APIConfig row yet.")
        return {}

    names = names or list(INDEX_SECURITY_IDS.keys())
    by_segment: dict[str, list[str]] = {}
    id_to_name = {}
    for name in names:
        info = INDEX_SECURITY_IDS.get(name)
        if not info:
            continue
        by_segment.setdefault(info["segment"], []).append(info["security_id"])
        id_to_name[(info["segment"], info["security_id"])] = name

    if not by_segment:
        return {}

    try:
        base = (cfg.base_url or BASE_URL).rstrip("/")
        resp = requests.post(
            f"{base}/marketfeed/quote",
            headers=_headers(cfg),
            json=by_segment,
            timeout=8,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        logger.warning(f"Dhan index quote fetch failed: {e}")
        return {}

    results = {}
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    for segment, entries in data.items():
        if not isinstance(entries, dict):
            continue
        for sec_id, quote in entries.items():
            name = id_to_name.get((segment, str(sec_id)))
            if name:
                results[name] = quote
    return results


def fetch_option_expiries(underlying: str) -> list[str]:
    """Available expiry dates for an underlying's option chain (empty list
    if unconfigured, unknown underlying, or on any error)."""
    cfg = _get_config()
    info = INDEX_SECURITY_IDS.get(underlying)
    if not cfg or not info:
        return []
    try:
        base = (cfg.base_url or BASE_URL).rstrip("/")
        resp = requests.post(
            f"{base}/optionchain/expirylist",
            headers=_headers(cfg),
            json={"UnderlyingScrip": int(info["security_id"]), "UnderlyingSeg": info["segment"]},
            timeout=8,
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("data", []) if isinstance(payload, dict) else []
    except Exception as e:
        logger.warning(f"Dhan option expiry fetch failed for {underlying}: {e}")
        return []


def fetch_option_chain(underlying: str, expiry: str) -> dict:
    """Full option chain (all strikes, both legs) for one underlying +
    expiry. Returns {} if unconfigured, unknown underlying, or on error."""
    cfg = _get_config()
    info = INDEX_SECURITY_IDS.get(underlying)
    if not cfg or not info:
        return {}
    try:
        base = (cfg.base_url or BASE_URL).rstrip("/")
        resp = requests.post(
            f"{base}/optionchain",
            headers=_headers(cfg),
            json={
                "UnderlyingScrip": int(info["security_id"]),
                "UnderlyingSeg": info["segment"],
                "Expiry": expiry,
            },
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("data", {}) if isinstance(payload, dict) else {}
    except Exception as e:
        logger.warning(f"Dhan option chain fetch failed for {underlying}@{expiry}: {e}")
        return {}
