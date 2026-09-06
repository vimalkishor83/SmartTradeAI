"""Contract checks for the market-heavy Asset Detail page."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "asset" / "detail.html"


def test_asset_detail_uses_data_actions_instead_of_inline_handlers():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "onchange=" not in source
    assert "data-asset-tab=\"chart\"" in source
    assert "data-sidebar-tab=\"overview\"" in source
    assert "function wireAssetControls()" in source
    assert "document.getElementById('askAiBtn')?.addEventListener('click', submitAskAi)" in source
    assert "document.getElementById('clLogBtn')?.addEventListener('click', logChecklist)" in source


def test_asset_detail_escapes_dynamic_content_and_validates_navigation():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'const ASSET_NAME   = "{{ asset.symbol }}"' not in source
    assert "const ASSET_NAME   = {{ asset.symbol | tojson }};" in source
    assert "onclick=\"location='/asset/${it.id}'\"" not in source
    assert "onclick=\"location='/asset/${s.asset_id}'\"" not in source
    assert "href=\"/asset/${a.asset_id}\"" not in source
    assert "STSafe.assetHref(it.id)" in source
    assert "STSafe.assetHref(id)" in source
    assert "STSafe.html(it.symbol)" in source
    assert "_escHtml(res.answer)" in source
    assert "_escHtml(d?.error" in source


def test_asset_detail_serializes_requests_and_handles_malformed_responses():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "let _askAiInFlight = false;" in source
    assert "if (!input || !btn || !out || !question || _askAiInFlight) return;" in source
    assert "Array.isArray(d.checks)" in source
    assert "Array.isArray(data.target_allocations)" in source
    assert "Array.isArray(data.reasoning_detail)" in source
    assert "el.dataset.loading === 'true'" in source
    assert "box.querySelector('#dcaRefreshBtn')?.addEventListener('click', loadDcaSetup)" in source
