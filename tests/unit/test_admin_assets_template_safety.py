"""Contract checks for provider values rendered by the admin Assets page."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "admin" / "assets.html"


def test_asset_table_and_catalog_escape_values_and_remove_inline_handlers():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'onchange="toggleAssetActive(' not in source
    assert 'onclick="removeAsset(' not in source
    assert 'onclick="toggleDeltaCatalogEntry(' not in source
    assert '${a.symbol}' not in source
    assert '${a.name ||' not in source
    assert '${r.symbol}' not in source
    assert '${r.name}' not in source
    assert 'data-action="toggle-active"' in source
    assert 'data-action="remove-asset"' in source
    assert 'class="asset-add-btn"' in source
    assert 'STSafe.html(c.symbol)' in source
    assert 'STSafe.html(r.name)' in source


def test_catalog_and_search_buttons_are_wired_from_dataset_values():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "el.addEventListener('click', () => toggleDeltaCatalogEntry" in source
    assert "button.addEventListener('click', () => addAsset" in source
    assert "button.dataset.symbol" in source
