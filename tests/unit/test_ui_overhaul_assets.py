from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_shared_ui_layer_is_loaded_after_existing_app_styles():
    base = (ROOT / "frontend" / "templates" / "partials" / "base.html").read_text(encoding="utf-8")
    assert 'href="/static/css/main.css' in base
    assert 'href="/static/css/ui-overhaul.css' in base
    assert base.index('href="/static/css/ui-overhaul.css') > base.index('href="/static/css/main.css')


def test_public_and_legal_pages_load_the_shared_ui_layer():
    landing = (ROOT / "frontend" / "templates" / "landing.html").read_text(encoding="utf-8")
    assert 'href="/static/css/ui-overhaul.css' in landing

    for path in (ROOT / "frontend" / "templates" / "legal").glob("*.html"):
        source = path.read_text(encoding="utf-8")
        assert 'href="/static/css/ui-overhaul.css' in source, path.name


def test_ui_layers_keep_the_two_frontends_neutral_and_responsive():
    primary = (ROOT / "frontend" / "static" / "css" / "ui-overhaul.css").read_text(encoding="utf-8")
    terminal_index = (ROOT / "frontend-Terminal" / "index.html").read_text(encoding="utf-8")
    terminal = (ROOT / "frontend-Terminal" / "css" / "ui-overhaul.css").read_text(encoding="utf-8")

    assert "--ui-black: #0b0b0b" in primary
    assert "@media (max-width: 680px)" in primary
    assert "/terminal/css/ui-overhaul.css" in terminal_index
    assert "--bg-0: #f2f2f2" in terminal
    assert "@media (prefers-reduced-motion: reduce)" in terminal
