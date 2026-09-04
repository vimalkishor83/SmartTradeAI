"""Cache-backed accessor for the singleton PlatformConfig row — used both
by the nav-visibility context processor (every page render) and by every
display-timeframe consumer (ta_summary/ai_ratings/ema_mtf/terminal), so it
must stay cheap."""
from app.extensions import cache

_CACHE_KEY = "platform_config"

# Every real market-data source in this app (Delta Exchange, Binance
# fallback, Yahoo) only knows how to fetch these intervals — see the
# INTERVAL/TF_INTERVAL maps in app/services/data/fetcher.py. The admin's
# Platform Config timeframe list is a free-text-ish reorderable set (an
# admin could type "1w" or a typo), so every consumer intersects against
# this fixed universe rather than trusting the config list directly —
# otherwise a non-fetchable entry would silently produce an empty/broken
# column instead of just being skipped.
FETCHABLE_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"]


def get_platform_config() -> dict:
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return cached
    from app.models.platform_config import PlatformConfig
    data = PlatformConfig.get_singleton().to_dict()
    cache.set(_CACHE_KEY, data, timeout=3600)
    return data


def get_display_timeframes() -> list[str]:
    """The admin-configured timeframe list, order preserved, intersected
    against what a data source can actually fetch. Falls back to the full
    fetchable universe if the admin list is empty or has no fetchable
    entries, so a misconfiguration degrades to "show everything" rather
    than silently emptying every timeframe-driven page."""
    configured = get_platform_config().get("timeframes") or []
    fetchable_set = set(FETCHABLE_TIMEFRAMES)
    result = [tf for tf in configured if tf in fetchable_set]
    return result or list(FETCHABLE_TIMEFRAMES)


def get_terminal_default_timeframe() -> str:
    """Which tab Terminal pre-selects on load. Falls back to '1h' if
    that's actually available, else the first configured timeframe --
    covers an admin picking a default and later removing it from the
    timeframe list, or removing '1h' itself, without leaving Terminal
    with no active tab at all (see terminal.html's own JS-side fallback
    for the client-side half of this same guard)."""
    available = get_display_timeframes()
    configured = get_platform_config().get("terminal_default_timeframe") or "1h"
    if configured in available:
        return configured
    return "1h" if "1h" in available else (available[0] if available else "1h")


def is_smc_order_block_enabled() -> bool:
    return bool(get_platform_config().get("smc_order_block_gate_enabled"))


def is_smc_liquidity_sweep_enabled() -> bool:
    return bool(get_platform_config().get("smc_liquidity_sweep_gate_enabled"))


def is_smc_support_resistance_enabled() -> bool:
    return bool(get_platform_config().get("smc_support_resistance_gate_enabled"))


def invalidate_platform_config():
    cache.delete(_CACHE_KEY)
