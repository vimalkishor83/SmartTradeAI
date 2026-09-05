"""Contract checks for shared UI widgets rendered from API responses."""

from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_core_widgets_do_not_interpolate_untrusted_text_into_html():
    source = (ROOT / "frontend" / "static" / "js" / "app.js").read_text(encoding="utf-8")

    assert "${message}" not in source
    assert "${n.title}" not in source
    assert "${n.message}" not in source
    assert "onclick=\"Notifications.markRead(" not in source
    assert 'data-symbol="${item.symbol}"' not in source
    assert "querySelectorAll(`[data-symbol=\"${tick.symbol}\"]`)" not in source
    assert "item.addEventListener('click'" in source
    assert "el.querySelector('span').textContent" in source


def test_command_palette_escapes_asset_values_and_ids():
    source = (ROOT / "frontend" / "templates" / "partials" / "base.html").read_text(encoding="utf-8")

    assert 'href="/asset/${a.id}"' not in source
    assert "${a.symbol}" not in source
    assert "${a.name || ''}" not in source
    assert "STSafe.assetHref(a.id)" in source
    assert "STSafe.html(a.symbol)" in source
    assert "STSafe.html(a.name || '')" in source
