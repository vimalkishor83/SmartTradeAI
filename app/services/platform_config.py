"""Cache-backed accessor for the singleton PlatformConfig row — used both
by the nav-visibility context processor (every page render) and by
ema_mtf.py's timeframe resolution, so it must stay cheap."""
from app.extensions import cache

_CACHE_KEY = "platform_config"


def get_platform_config() -> dict:
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return cached
    from app.models.platform_config import PlatformConfig
    data = PlatformConfig.get_singleton().to_dict()
    cache.set(_CACHE_KEY, data, timeout=3600)
    return data


def invalidate_platform_config():
    cache.delete(_CACHE_KEY)
