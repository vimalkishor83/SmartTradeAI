"""Contract checks for the UI-3 shared application shell."""

from pathlib import Path


ROOT = Path(__file__).parents[2]
BASE = ROOT / "frontend" / "templates" / "partials" / "base.html"
ASK_AI = ROOT / "frontend" / "static" / "js" / "global_ask_ai.js"


def test_shell_controls_have_explicit_accessible_names_and_relationships():
    source = BASE.read_text(encoding="utf-8")

    assert 'aria-labelledby="sidebarLabel"' in source
    assert 'id="sidebarLabel"' in source
    assert 'aria-label="Primary application sections"' in source
    assert 'aria-label="Open navigation"' in source
    assert 'aria-label="Open command palette"' in source
    assert 'aria-controls="cmdOverlay"' in source
    assert 'aria-label="Switch to light theme"' in source
    assert 'aria-label="Notifications"' in source
    assert 'aria-modal="true"' in source
    assert 'aria-labelledby="cmdPaletteTitle"' in source
    assert 'aria-controls="cmdResults"' in source
    assert 'aria-label="Open Ask AI"' in source
    assert "sidebarCollapsed = localStorage.getItem('sidebar_collapsed')" in source


def test_shell_state_changes_are_keyboard_and_storage_safe():
    source = BASE.read_text(encoding="utf-8")
    ask_ai = ASK_AI.read_text(encoding="utf-8")

    assert "backdrop?.setAttribute('aria-hidden', 'false')" in source
    assert "mobileBtn?.setAttribute('aria-label', 'Close navigation')" in source
    assert "try { saved = localStorage.getItem(key); } catch {}" in source
    assert "} catch (_) {}" in source
    assert "lastFocus = document.activeElement" in source
    assert "overlay.setAttribute('aria-hidden', 'false')" in source
    assert "overlay.setAttribute('aria-hidden', 'true')" in source
    assert "focusable[next].focus()" in source
    assert "if (lastFocus && typeof lastFocus.focus === 'function') lastFocus.focus();" in source
    assert "e.preventDefault(); open();" in source
    assert "popup.setAttribute('aria-hidden', 'false')" in ask_ai
    assert "popup.setAttribute('aria-hidden', 'true')" in ask_ai
    assert "fab.setAttribute('aria-expanded', 'true')" in ask_ai
    assert "fab.setAttribute('aria-expanded', 'false')" in ask_ai
    assert "if (lastFocus && typeof lastFocus.focus === 'function') lastFocus.focus();" in ask_ai
