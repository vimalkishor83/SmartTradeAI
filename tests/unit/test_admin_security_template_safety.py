"""Contract checks for safe and duplicate-resistant Security controls."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "admin" / "security.html"


def test_security_actions_are_bound_without_inline_handlers():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "onchange=" not in source
    assert "type=\"button\"" in source
    assert "document.getElementById('saveSecurityBtn').addEventListener('click', saveSecurity)" in source
    assert "document.getElementById('saveSecurityTelegramBtn').addEventListener('click', saveSecurityTelegram)" in source
    assert "document.getElementById('testSecurityTelegramBtn').addEventListener('click', testSecurityTelegram)" in source


def test_security_inputs_match_backend_contract_and_prevent_duplicate_requests():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "Number.isSafeInteger(value)" in source
    assert "minutes < 5 || minutes > 43200" in source
    assert "if (chatId && !/^-?\\d+$/.test(chatId))" in source
    assert "if (_securitySaveInFlight) return;" in source
    assert "if (_securityTelegramTestInFlight) return;" in source
