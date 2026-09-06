"""Contract checks for safe Telegram Alerts rendering and controls."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "admin" / "telegram_alerts.html"


def test_channel_values_are_escaped_and_names_are_not_embedded_in_handlers():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "${c.name}" not in source
    assert "deleteChannel(${c.id}" not in source
    assert "STSafe.html(c.name || '')" in source
    assert "data-channel-name=" in source
    assert "STSafe.assetId(c.id)" in source
    assert "STSafe.html(tf)" in source


def test_telegram_controls_use_event_bindings():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "saveIndividualBtn').addEventListener" in source
    assert "addChannelBtn').addEventListener" in source
    assert "saveChannelBtn').addEventListener" in source
    assert "button.addEventListener('click'" in source
