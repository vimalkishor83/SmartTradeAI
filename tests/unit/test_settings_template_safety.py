"""Contract checks for the account Settings workflow."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "settings.html"


def test_settings_controls_do_not_use_inline_event_handlers():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "onchange=" not in source
    assert "data-action=\"setup-2fa\"" in source
    assert "data-action=\"confirm-2fa\"" in source
    assert "data-market-action=\"select\"" in source
    assert "data-request-plan=\"${settingsText(p.name)}\"" in source


def test_settings_dynamic_values_are_escaped_and_mutations_are_serialized():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "function settingsText(value)" in source
    assert "function settingsAssetId(value)" in source
    assert "function settingsNumber(value, fallback = 0)" in source
    assert "settingsText(a.symbol)" in source
    assert "settingsText(a.name)" in source
    assert "settingsText(p.name)" in source
    assert "let _settingsMutations = new Set();" in source
    assert "_settingsMutations.has('plan:' + plan.toLowerCase())" in source
    assert "Array.isArray(res?.backup_codes)" in source
