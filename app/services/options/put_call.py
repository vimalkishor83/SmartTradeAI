"""
Put/call ratio via Deribit's public API — free, keyless, crypto options only.

CBOE's free CSV put/call feeds (totalpc.csv / equitypc.csv) were checked
during development and found to be FROZEN since October 2019 — not a
usable "delayed" data source, just abandoned files. No other free,
keyless equity/index options feed was found. This module is honestly
scoped to crypto (BTC/ETH) options via Deribit only, rather than showing
fabricated or years-stale "equity" numbers next to it.
"""
from __future__ import annotations
import logging
import requests

logger = logging.getLogger(__name__)

DERIBIT_URL = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
CURRENCIES = ["BTC", "ETH"]


def _fetch_currency_summary(currency: str) -> dict | None:
    try:
        resp = requests.get(
            DERIBIT_URL,
            params={"currency": currency, "kind": "option"},
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("result")
    except Exception as e:
        logger.warning(f"Deribit fetch failed for {currency}: {e}")
        return None


def fetch_put_call_ratio() -> dict:
    """
    Returns per-currency (BTC, ETH) put/call ratios computed from Deribit's
    live options book: open interest and 24h volume split by option type
    (instrument names end in -C for calls, -P for puts).
    """
    instruments = []
    for ccy in CURRENCIES:
        summary = _fetch_currency_summary(ccy)
        if not summary:
            instruments.append({
                "currency": ccy,
                "available": False,
                "put_call_oi_ratio": None,
                "put_call_volume_ratio": None,
            })
            continue

        call_oi = put_oi = call_vol = put_vol = 0.0
        for row in summary:
            name = row.get("instrument_name", "")
            oi = row.get("open_interest") or 0
            vol = row.get("volume") or 0
            if name.endswith("-C"):
                call_oi += oi
                call_vol += vol
            elif name.endswith("-P"):
                put_oi += oi
                put_vol += vol

        instruments.append({
            "currency": ccy,
            "available": True,
            "call_open_interest": round(call_oi, 2),
            "put_open_interest": round(put_oi, 2),
            "put_call_oi_ratio": round(put_oi / call_oi, 3) if call_oi else None,
            "call_volume_24h": round(call_vol, 2),
            "put_volume_24h": round(put_vol, 2),
            "put_call_volume_ratio": round(put_vol / call_vol, 3) if call_vol else None,
        })

    return {
        "instruments": instruments,
        "source": "Deribit (live)",
        "scope": "crypto-only",
        "note": "Equity/index put-call data (CBOE) has no working free feed as of this build — CBOE's public CSVs stopped updating in 2019. Crypto (BTC/ETH) options only, live from Deribit.",
    }
