from app.services.notifications.telegram_individual_signal_limits import _allows


def test_empty_policy_defaults_to_allow_all():
    assert _allows({"enabled": True, "asset_ids": None, "timeframes": None}, 42, "15m")


def test_policy_can_allow_only_selected_asset_and_timeframe():
    settings = {"enabled": True, "asset_ids": [42], "timeframes": ["15m", "1h"]}

    assert _allows(settings, 42, "15m")
    assert not _allows(settings, 43, "15m")
    assert not _allows(settings, 42, "5m")


def test_disabled_or_empty_policy_blocks_delivery():
    assert not _allows({"enabled": False, "asset_ids": None, "timeframes": None}, 42, "15m")
    assert not _allows({"enabled": True, "asset_ids": [], "timeframes": None}, 42, "15m")
    assert not _allows({"enabled": True, "asset_ids": None, "timeframes": []}, 42, "15m")
