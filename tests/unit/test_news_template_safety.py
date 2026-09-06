"""Contract checks for provider-controlled values rendered by the News page."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "news.html"


def test_news_template_escapes_provider_values_and_rejects_unsafe_links():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "function escapeHtml(value)" in source
    assert "function safeExternalUrl(value)" in source
    assert "['http:', 'https:'].includes(url.protocol)" in source
    assert '${n.title}' not in source
    assert '${n.source}' not in source
    assert '${n.summary}' not in source
    assert '${n.url}' not in source
    assert '${e.title}' not in source
    assert '${e.forecast}' not in source
    assert '${e.previous}' not in source
    assert '${e.actual}' not in source


def test_news_template_delegates_pagination_and_ignores_stale_refreshes():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert 'data-page="${i}"' in source
    assert "pagination.addEventListener('click'" in source
    assert "_newsSequence" in source
    assert "_econSequence" in source
    assert "Promise.allSettled([loadNews(1), loadEcon()])" in source
    assert "events.slice(0, 250)" in source
    assert 'id="econBody" role="status" aria-live="polite"' in source
    assert "Calendar temporarily unavailable. Try refreshing." in source
