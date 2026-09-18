from pathlib import Path


APP_JS = Path(__file__).parents[2] / "frontend" / "static" / "js" / "app.js"
BASE = Path(__file__).parents[2] / "frontend" / "templates" / "partials" / "base.html"


def test_live_price_client_uses_admin_interval_without_overlapping_requests():
    source = APP_JS.read_text(encoding="utf-8")

    assert "_seedInFlight" in source
    assert "live_price_refresh_interval_seconds" in source
    assert "document.visibilityState !== 'hidden'" in source
    assert "this.update(t)" in source
    assert "Ticker.patchItem(t)" in source


def test_base_template_exposes_only_the_safe_live_price_setting():
    source = BASE.read_text(encoding="utf-8")

    assert "window.PLATFORM_CONFIG" in source
    assert "live_price_refresh_interval_seconds" in source

def test_websocket_status_recovers_after_background_tab_resume():
    source = APP_JS.read_text(encoding="utf-8")

    assert "document.visibilityState === 'hidden'" in source
    assert "visibilitychange" in source
    assert "_wsResumeGraceUntil" in source
    assert "_wsSetStatus('live')" in source
    assert "_wsStartFreshnessWatch();" in source
