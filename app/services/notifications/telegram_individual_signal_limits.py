"""Cached policy for personal signal-related Telegram delivery."""

from app.extensions import cache


_CACHE_KEY = "telegram_individual_signal_limits"
_CACHE_SECONDS = 60


def get_telegram_individual_signal_limits():
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return cached

    from app.models.telegram_individual_signal_limit import TelegramIndividualSignalLimit

    data = TelegramIndividualSignalLimit.get_singleton().to_dict()
    cache.set(_CACHE_KEY, data, timeout=_CACHE_SECONDS)
    return data


def individual_signal_allowed(asset_id, timeframe):
    """Return whether a personal signal alert may be delivered.

    This policy is separate from PlatformConfig market gates and from
    TelegramAlertChannel group routing. It covers signal, lifecycle, close,
    and timeframe rating-change alerts sent to individual chats.
    """
    try:
        asset_id = int(asset_id)
    except (TypeError, ValueError):
        return False
    return _allows(get_telegram_individual_signal_limits(), asset_id, timeframe)


def _allows(settings, asset_id, timeframe):
    if not settings.get("enabled", True):
        return False
    asset_ids = settings.get("asset_ids")
    if asset_ids is not None and asset_id not in {int(value) for value in asset_ids}:
        return False
    timeframes = settings.get("timeframes")
    if timeframes is not None and timeframe not in timeframes:
        return False
    return True


def invalidate_telegram_individual_signal_limits():
    cache.delete(_CACHE_KEY)
