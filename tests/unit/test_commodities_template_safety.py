"""Contract checks for the Commodities market workflow."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "markets" / "commodities.html"


def test_commodities_controls_do_not_use_inline_handlers():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "onchange=" not in source
    assert "oninput=" not in source
    assert 'data-action="generate-commodity"' in source
    assert 'data-action="load-sentiment"' in source
    assert 'data-action="commodity-page"' in source


def test_commodities_validate_and_bound_dynamic_values():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "function commodityNumber(value, fallback = 0)" in source
    assert "function commodityPercent(value)" in source
    assert "normalizeCommoditySignal" in source
    assert "STSafe.html(s.asset)" in source
    assert "STSafe.html(String(s.confidence_label" in source
    assert "let _commodityMutations = new Set();" in source


def test_commodities_guard_concurrent_reads_and_generation():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "let _signalLoadSequence = 0;" in source
    assert "if (sequence !== _signalLoadSequence) return;" in source
    assert "const mutationKey = `signal:${symbol}:${tf}`;" in source
    assert "const mutationKey = 'signals:all';" in source
    assert "renderCommodityPagination(page, total);" in source
