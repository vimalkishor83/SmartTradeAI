"""Best-effort IP -> city/country lookup for visitor security alerts.

Never raises and never blocks a request for long — a failed or slow
lookup must not affect the homepage response. Private/local addresses
(dev machines, health checks behind the load balancer) are skipped
without a network call since a lookup for them is meaningless.
"""
import ipaddress
import logging

import requests

logger = logging.getLogger(__name__)

_LOOKUP_URL = "http://ip-api.com/json/{ip}"
_TIMEOUT_SECONDS = 3


def lookup_location(ip_address: str) -> str:
    """Returns "City, Country" or "" if unavailable/private/lookup failed."""
    if not ip_address:
        return ""
    try:
        addr = ipaddress.ip_address(ip_address)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            return ""
    except ValueError:
        return ""

    try:
        resp = requests.get(
            _LOOKUP_URL.format(ip=ip_address),
            params={"fields": "status,city,country"},
            timeout=_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            return ""
        city = (data.get("city") or "").strip()
        country = (data.get("country") or "").strip()
        return ", ".join(part for part in (city, country) if part)
    except Exception as exc:
        logger.info("IP geolocation lookup failed for %s: %s", ip_address, type(exc).__name__)
        return ""
