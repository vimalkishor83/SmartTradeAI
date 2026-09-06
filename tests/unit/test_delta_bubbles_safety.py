"""Contract checks for safe Delta Bubbles rendering and refreshes."""

from pathlib import Path


BUBBLES = Path(__file__).parents[2] / "frontend" / "static" / "js" / "pages" / "delta_bubbles.js"


def test_delta_bubbles_escapes_provider_labels_and_values():
    source = BUBBLES.read_text(encoding="utf-8")

    assert "${b.label}" not in source
    assert "${b.symbol}" not in source
    assert "${b.change_pct}" not in source
    assert "STSafe.html(title)" in source
    assert "STSafe.html(ticker)" in source
    assert "STSafe.html(b.label || b.symbol || '')" in source
    assert "Array.isArray(data?.bubbles)" in source


def test_delta_bubbles_validates_groups_and_suppresses_duplicate_refreshes():
    source = BUBBLES.read_text(encoding="utf-8")

    assert "const DB_GROUPS = new Set" in source
    assert "if (dbLoadInFlight) return;" in source
    assert "encodeURIComponent(DB_GROUPS.has(dbGroup) ? dbGroup : 'major')" in source
    assert "finally {\n    dbLoadInFlight = false;" in source
    assert "dbGroup = DB_GROUPS.has(btn.dataset.group) ? btn.dataset.group : 'major';" in source
    assert "STSafe.html(btn.textContent.trim())" in source
