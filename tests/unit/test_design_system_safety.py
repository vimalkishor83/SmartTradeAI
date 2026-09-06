"""Contract checks for the shared UI-2 design system foundation."""

from pathlib import Path


ROOT = Path(__file__).parents[2]
CSS = ROOT / "frontend" / "static" / "css" / "main.css"
BASE = ROOT / "frontend" / "templates" / "partials" / "base.html"


def test_shared_design_tokens_and_primitives_are_available():
    css = CSS.read_text(encoding="utf-8")

    for token in (
        "--surface-page",
        "--surface-card",
        "--focus-ring",
        "--success",
        "--danger",
        "--warning",
        "--info",
        "--control-height",
        "--z-overlay",
    ):
        assert token in css

    for primitive in (
        ".ui-surface",
        ".ui-toolbar",
        ".ui-state",
        ".ui-state[hidden]",
        ".ui-table-wrap",
        ".ui-chip",
        ".ui-metric",
        ".ui-visually-hidden",
    ):
        assert primitive in css

    assert ".section-card::after" in css
    assert "color-mix(in srgb, var(--accent) 24%, transparent)" in css


def test_shared_shell_exposes_accessible_focus_and_motion_contracts():
    css = CSS.read_text(encoding="utf-8")
    base = BASE.read_text(encoding="utf-8")

    assert '<body class="app-shell' in base
    assert '.app-shell :where(a, button, input, select, textarea, summary):focus-visible' in css
    assert '@media (prefers-reduced-motion: reduce)' in css
    assert 'color-scheme: dark' in css
    assert 'color-scheme: light' in css
