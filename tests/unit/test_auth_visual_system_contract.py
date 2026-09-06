"""Protect the shared authentication visual and responsive contract."""

from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_auth_pages_load_shared_styles_and_use_shared_layout_hook():
    base = (ROOT / "frontend/templates/partials/base.html").read_text(encoding="utf-8")
    assert "/static/css/auth.css" in base
    assert "auth-shell" in base

    for page in ("login.html", "register.html", "forgot_password.html"):
        source = (ROOT / "frontend/templates/auth" / page).read_text(encoding="utf-8")
        assert 'class="auth-container has-auth-side"' in source


def test_shared_auth_styles_cover_keyboard_focus_and_mobile_layout():
    source = (ROOT / "frontend/static/css/auth.css").read_text(encoding="utf-8")
    assert ".auth-shell a:focus-visible" in source
    assert ".auth-shell .auth-container.has-auth-side" in source
    assert ".auth-shell .auth-simple-card::after" in source
    assert "prefers-reduced-motion" in source
    assert "min-height: 46px" in source
