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


def test_shared_shell_exposes_route_aware_visual_atmosphere():
    css = CSS.read_text(encoding="utf-8")
    base = BASE.read_text(encoding="utf-8")

    assert 'data-active="{{ active|default(\'dashboard\') }}"' in base
    assert ".page-content::before" in css
    assert ".app-shell .page-content > *" in css
    assert "isolation: isolate" in css
    assert "markets-atmosphere.png" in css
    assert "legal-center-atmosphere.png" in css


def test_shared_shell_exposes_editorial_module_labels_and_wave_accent():
    css = CSS.read_text(encoding="utf-8")

    assert "#pageContentBody::before" in css
    assert "01 / MARKET OVERVIEW" in css
    assert "02 / SIGNAL DISCOVERY" in css
    assert "05 / CAPITAL CONTROL" in css
    assert ".dash-header::after" in css


def test_light_theme_has_a_complete_shell_finish():
    css = CSS.read_text(encoding="utf-8")

    assert 'html[data-theme="light"] .app-shell .top-navbar' in css
    assert 'html[data-theme="light"] .app-shell .ticker-strip' in css
    assert 'html[data-theme="light"] .app-shell .sidebar' in css
    assert 'html[data-theme="light"] .app-shell .section-card' in css
    assert 'html[data-theme="light"] .app-shell .form-control' in css
    assert 'html[data-theme="light"] select option' in css


def test_light_theme_keeps_analysis_insight_strips_readable():
    css = CSS.read_text(encoding="utf-8")

    for selector in (
        '[data-theme="light"] .app-shell .analysis-insight-strip',
        '[data-theme="light"] .app-shell .analysis-insight-lead strong',
        '[data-theme="light"] .app-shell .analysis-insight-item',
    ):
        assert selector in css

    assert "#0b1220" in css
    assert "#40516a" in css
