"""Regression coverage for a real, live-confirmed bug: openai/gpt-oss-20b
(a reasoning model) spends part of max_tokens on an internal trace before
producing any content. At the previous max_tokens=120 budget, every call
returned finish_reason="length" with empty content -- confirmed against a
real Groq account. See app/services/ai/llm_reasoning.py.
"""

from unittest.mock import Mock, patch

from app.services.ai.llm_reasoning import (
    _call_openai_compatible,
    generate_reasoning,
    answer_asset_question,
)


def _groq_response(content, finish_reason="stop", reasoning_tokens=0):
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": {"completion_tokens_details": {"reasoning_tokens": reasoning_tokens}},
    }


def test_reasoning_model_exhausting_budget_on_thinking_returns_empty_not_an_error():
    """The low-level call must not raise or crash when a reasoning model
    burns its whole budget -- it returns an empty string, same as before,
    but now also logs a warning identifying the cause."""
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = _groq_response("", finish_reason="length", reasoning_tokens=120)

    with patch("app.services.ai.llm_reasoning.requests.post", return_value=mock_resp):
        result = _call_openai_compatible(
            "https://api.groq.com/openai/v1", "fake-key", "openai/gpt-oss-20b", "prompt", max_tokens=120,
        )

    assert result == ""


def test_sufficient_budget_returns_real_content():
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = _groq_response(
        "The bullish crossover supports this entry.", finish_reason="stop", reasoning_tokens=169,
    )

    with patch("app.services.ai.llm_reasoning.requests.post", return_value=mock_resp):
        result = _call_openai_compatible(
            "https://api.groq.com/openai/v1", "fake-key", "openai/gpt-oss-20b", "prompt", max_tokens=500,
        )

    assert result == "The bullish crossover supports this entry."


def test_generate_reasoning_requests_enough_tokens_for_a_reasoning_model():
    """The exact regression: generate_reasoning() must not go back to
    requesting only ~120 tokens, which live-tested empty on this model."""
    with patch("app.services.ai.llm_reasoning._get_config") as mock_cfg:
        mock_cfg.return_value = Mock(
            provider="groq", base_url=None, config={}, get_api_key=lambda: "fake-key",
        )
        with patch("app.services.ai.llm_reasoning._call_openai_compatible") as mock_call:
            mock_call.return_value = "Reasonable narrative."
            generate_reasoning("BUY", "BTCUSDT", "1h", 78.0, "trending", [])

    requested_max_tokens = mock_call.call_args[0][-1]
    assert requested_max_tokens >= 400


def test_answer_asset_question_requests_enough_tokens_for_a_reasoning_model():
    with patch("app.services.ai.llm_reasoning._get_config") as mock_cfg:
        mock_cfg.return_value = Mock(
            provider="groq", base_url=None, config={}, get_api_key=lambda: "fake-key",
        )
        with patch("app.services.ai.llm_reasoning._call_openai_compatible") as mock_call:
            mock_call.return_value = "A grounded answer."
            answer_asset_question("BTCUSDT", "crypto", "Why did it move?", {"price": 100})

    requested_max_tokens = mock_call.call_args[0][-1]
    assert requested_max_tokens >= 600
