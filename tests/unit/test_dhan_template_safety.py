from pathlib import Path


TEMPLATE = Path("frontend/templates/dashboard/dhan_indices.html")


def test_dhan_template_validates_and_escapes_provider_values():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "onchange=" not in source
    assert "dhanEscape" in source
    assert "dhanNumber" in source
    assert "_dhanRunSequence" in source
    assert "_dhanChainSequence" in source
    assert ".slice(0, 500)" in source
    assert "Promise.all([loadDhanIndices(run), loadDhanExpiries(run)])" in source
