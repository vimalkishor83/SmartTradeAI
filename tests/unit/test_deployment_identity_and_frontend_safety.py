"""Regression coverage for environment identity and frontend safety fixes."""

from pathlib import Path

from flask import Flask

from app.config import DevelopmentConfig
from app.tasks.notification_tasks import _telegram_disclaimer
from app.views import _site_url


ROOT = Path(__file__).parents[2]


def test_development_identity_is_not_inherited_from_production():
    assert DevelopmentConfig.PUBLIC_SITE_URL == "https://smarttradeai.info"
    assert DevelopmentConfig.SUPPORT_EMAIL == "support@smarttradeai.info"
    assert DevelopmentConfig.MAIL_DEFAULT_SENDER == "support@smarttradeai.info"
    assert DevelopmentConfig.VAPID_CLAIMS_EMAIL == "mailto:support@smarttradeai.info"


def test_views_read_the_active_public_site_url():
    app = Flask(__name__)
    app.config["PUBLIC_SITE_URL"] = "https://example.test/"

    with app.app_context():
        assert _site_url() == "https://example.test"


def test_telegram_disclaimer_uses_the_active_public_site_url():
    app = Flask(__name__)
    app.config["PUBLIC_SITE_URL"] = "https://smarttradeai.info"

    with app.app_context():
        text = _telegram_disclaimer()

    assert "https://smarttradeai.info/disclaimer" in text
    assert "smarttradeai.online/disclaimer" not in text


def test_public_templates_do_not_hardcode_the_production_identity():
    template_root = ROOT / "frontend" / "templates"
    public_templates = [
        template_root / "landing.html",
        *sorted((template_root / "auth").glob("*.html")),
        *sorted((template_root / "legal").glob("*.html")),
    ]

    for path in public_templates:
        source = path.read_text(encoding="utf-8")
        assert "https://smarttradeai.online" not in source, path
        assert "support@smarttradeai.online" not in source, path


def test_missing_alternate_frontends_fail_as_not_found():
    source = (ROOT / "app" / "frontends.py").read_text(encoding="utf-8")
    assert "if not os.path.isdir(directory):" in source
    assert "abort(404" in source
    assert "limiter.exempt(frontends_bp)" not in source


def test_push_assets_reference_files_that_exist():
    service_worker = (ROOT / "frontend" / "static" / "sw.js").read_text(encoding="utf-8")
    sender = (ROOT / "app" / "services" / "push" / "sender.py").read_text(encoding="utf-8")
    assert "/static/img/icon-192.png" in service_worker
    assert "/static/img/icon-192.png" in sender
    assert (ROOT / "frontend" / "static" / "img" / "icon-192.png").is_file()


def test_ask_ai_escapes_all_dynamic_response_text():
    source = (ROOT / "frontend" / "static" / "js" / "global_ask_ai.js").read_text(encoding="utf-8")
    assert "safeText(res.answer)" in source
    assert "safeText(res.message)" in source
    assert "safeText(res?.error" in source


def test_shared_refresh_helper_is_visible_state_aware_and_bounded():
    source = (ROOT / "frontend" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "window.STRefresh" in source
    assert "document.visibilityState !== 'hidden'" in source
    assert "Math.min(options.max || 3600" in source
