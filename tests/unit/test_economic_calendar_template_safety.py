"""Contract checks for the IST-aware Economic Calendar UI."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "economic_calendar.html"


def test_calendar_uses_event_bound_refresh_and_local_filtering():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert 'id="calRefreshBtn"' in source
    assert 'type="button"' in source
    assert 'id="calendarBody" role="status" aria-live="polite"' in source
    assert "let _calendarEvents = [];" in source
    assert "let _calendarLoading = false;" in source
    assert "if (_calendarLoading) return;" in source
    assert "document.getElementById('calDayFilter')?.addEventListener('change', renderCalendar)" in source


def test_calendar_uses_ist_dates_and_escapes_provider_values():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "function _calendarDate(value)" in source
    assert "function _calendarIstDay(date)" in source
    assert "_calendarIstDay(evDate) === todayIst" in source
    assert "${e.title || '—'}" not in source
    assert "${e.currency || e.country || ''}" not in source
    assert "_calendarHtml(e.title || '—')" in source
    assert "_calendarHtml(e.currency || e.country || '')" in source


def test_calendar_rejects_malformed_api_payloads():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "!data || data.error || !Array.isArray(data.events)" in source
    assert "data.events.filter(event => event && typeof event === 'object')" in source
    assert "const imp = String(e.impact || 'low').toLowerCase();" in source
    assert "button.setAttribute('aria-busy', 'true');" in source
    assert "button.setAttribute('aria-busy', 'false');" in source
    assert "catch (_)" in source
