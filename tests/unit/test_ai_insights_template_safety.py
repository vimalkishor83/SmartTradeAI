"""Contract checks for the AI Insights workflow."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "ai_insights.html"


def test_ai_insights_controls_are_event_bound():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "onchange=" not in source
    assert 'data-action="select-all-timeframes"' in source
    assert 'data-action="clear-all-timeframes"' in source
    assert "runAI')?.addEventListener('click', runPrediction)" in source


def test_ai_insights_validates_asset_and_prediction_payloads():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "const AI_TIMEFRAMES = new Set(Object.keys(TF_LABEL));" in source
    assert "Number.isInteger(id) || id < 1" in source
    assert "escapePredictionMeta(a.symbol)" in source
    assert "const bounded = value =>" in source
    assert "Array.isArray(data.model_outputs)" in source
    assert "STSafe.assetId(a.id)" in source
    assert "const entryLowRaw = data.entry_range_low" in source
    assert "const entryHighRaw = data.entry_range_high" in source
    assert "predicted_stop" in source
    assert "Best Long Entry Zone" in source
    assert "Best Short Entry Zone" in source
    assert "entry_zone_source" in source
    assert "limit reference only" in source
    assert "Trade map" in source
    assert "riskReward" in source
    assert "Invalidates at" in source


def test_ai_insights_serializes_run_lifecycle():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "let _predictionRunSequence = 0;" in source
    assert "let _predictionRunning = false;" in source
    assert "if (_predictionRunning) return;" in source
    assert "_predictionRunning = true;" in source
    assert "if (sequence !== _predictionRunSequence) return;" in source
    assert "Promise.all(selected.map(tf =>" in source


def test_ai_insights_exposes_prediction_context_and_unavailable_states():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'id="aiContext" role="status" aria-live="polite"' in source
    assert 'id="aiContent" aria-busy="false"' in source
    assert 'id="aiRightPanel" role="region" aria-live="polite"' in source
    assert 'for="aiAsset">Select Asset</label>' in source
    assert 'id="tfCheckboxGrid" role="group" aria-labelledby="aiTfLabel"' in source
    assert "function setAiBusy(busy)" in source
    assert "Assets temporarily unavailable" in source
    assert "Prediction results are incomplete" in source
    assert "try {\n    data = await API.get('/assets/');" in source
    assert "if (!panel || !btn) return;" in source


def test_ai_insights_persists_user_defaults():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'id="saveAiDefaults"' in source
    assert 'id="resetAiDefaults"' in source
    assert "API.get('/auth/me/ai-insights-preferences')" in source
    assert "API.put('/auth/me/ai-insights-preferences'" in source
    assert "Promise.all([loadAiPreferences(), loadAssets()])" in source
