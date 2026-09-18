"""Per-user override on top of the platform-wide Telegram category/market
gates in PlatformConfig. See app/models/telegram_user_preference.py for why
this is additive rather than a replacement for those gates."""

from app.extensions import cache

_CACHE_KEY_PREFIX = "telegram_user_pref:"
_CACHE_SECONDS = 60


def _cache_key(user_id):
    return f"{_CACHE_KEY_PREFIX}{user_id}"


def get_user_telegram_preference(user_id):
    cached = cache.get(_cache_key(user_id))
    if cached is not None:
        return cached

    from app.models.telegram_user_preference import TelegramUserPreference

    row = TelegramUserPreference.query.filter_by(user_id=user_id).first()
    data = row.to_dict() if row else {
        "user_id": user_id, "categories": None, "markets": None, "asset_ids": None,
    }
    cache.set(_cache_key(user_id), data, timeout=_CACHE_SECONDS)
    return data


def user_wants_telegram_category(user_id, category, market=None, asset_id=None):
    """True unless the user has an explicit per-user restriction that
    excludes this category/market/asset. A user with no configured
    preference always returns True here — this function only narrows,
    it never widens what PlatformConfig's gates already allow."""
    pref = get_user_telegram_preference(user_id)

    categories = pref.get("categories")
    if categories is not None and category not in categories:
        return False

    markets = pref.get("markets")
    if market is not None and markets is not None and market not in markets:
        return False

    asset_ids = pref.get("asset_ids")
    if asset_id is not None and asset_ids is not None:
        try:
            asset_id = int(asset_id)
        except (TypeError, ValueError):
            return False
        if asset_id not in {int(value) for value in asset_ids}:
            return False

    return True


def invalidate_user_telegram_preference(user_id):
    cache.delete(_cache_key(user_id))
