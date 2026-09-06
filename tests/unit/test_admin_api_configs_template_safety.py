"""Contract checks for safe admin API Configuration rendering and controls."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "admin" / "api_configs.html"


def test_provider_values_and_test_details_are_escaped():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "${c.name}" not in source
    assert "${c.provider}" not in source
    assert "${c.group_chat_id}" not in source
    assert "${detail}" not in source
    assert "escapeHtml(c.name)" in source
    assert "escapeHtml(providerLabel(p))" in source
    assert "escapeHtml(detail)" in source
    assert "escapeHtml(l.error_message || '—')" in source


def test_configuration_actions_are_bound_from_validated_ids():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "onchange=" not in source
    assert "data-config-action=\"edit\"" in source
    assert "data-config-action=\"delete\"" in source
    assert "bindConfigActions(wrap)" in source
    assert "STSafe.assetId(document.getElementById('cfgId').value)" in source
