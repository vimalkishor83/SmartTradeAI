"""Contract checks for safe admin Platform Configuration controls."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "admin" / "platform_config.html"


def test_platform_controls_do_not_use_inline_handlers():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "onchange=" not in source
    assert "id=\"refreshPlatformConfigBtn\"" in source
    assert 'id="platformConfigStatus"' in source
    assert "let configLoading = false;" in source
    assert "id=\"addTimeframeBtn\"" in source
    assert "data-timeframe-action=\"move\"" in source
    assert "data-timeframe-action=\"remove\"" in source
    assert "document.getElementById('tfChips').addEventListener('click'" in source


def test_configured_labels_and_timeframes_are_escaped():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "${group.label}" not in source
    assert "${label}" not in source
    assert "data-href=\"${href}\"" not in source
    assert "${tf}</span>" not in source
    assert "${tf}</option>" not in source
    assert "STSafe.html(group.label)" in source
    assert "STSafe.html(label)" in source
    assert "STSafe.html(href)" in source
    assert "STSafe.html(tf)" in source


def test_platform_save_paths_treat_api_errors_as_failures():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert source.count("if (res && !res.error)") >= 7
    assert "Number.isInteger(i)" in source
    assert "if (!tf) { Toast.show('Add at least one timeframe first'" in source
    assert "Unable to load configuration. Try Refresh." in source
    assert "refresh.setAttribute('aria-busy', 'false')" in source
