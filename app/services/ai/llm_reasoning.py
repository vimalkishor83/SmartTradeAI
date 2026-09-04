"""LLM-written "why this signal" narrative — an optional upgrade over the
deterministic, template-joined reasoning string SignalEngine already
produces from reasoning_detail (the scored, aligned/not-aligned factors).

Deliberately NOT in the hot path: SignalEngine.generate_signal()/analyze()
run on every asset x every timeframe x every scan cycle (including every
HOLD that never becomes a real signal) -- calling an LLM there would blow
through any free-tier rate limit almost immediately. This is called only
from the two places a signal actually gets PERSISTED (a genuine BUY/SELL
that passed every gate): generate_signals_for_timeframe() in
app/tasks/signal_tasks.py, and _open_live_read_log() in
app/api/v1/signals.py -- both already infrequent relative to the engine's
own per-candle evaluation rate.

Configured the same way as every other integration this session (Dhan,
etc.): via Admin > API Configurations, market="ai", provider one of
groq/gemini/openrouter. Until a real key is saved there, is_configured()
returns False and every caller keeps using the existing deterministic
reasoning string -- this can only ever add polish, never break anything
or change what signal gets generated.
"""
from __future__ import annotations

import logging
import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 10  # seconds -- a slow/hanging LLM call must never stall the
               # signal-generation job for every other asset behind it.


def _get_config():
    from app.models.api_config import APIConfig
    return (APIConfig.query
            .filter_by(market="ai", is_active=True, status="active")
            .order_by(APIConfig.is_default.desc(), APIConfig.priority.desc())
            .first())


def is_configured() -> bool:
    try:
        cfg = _get_config()
        return bool(cfg and cfg.get_api_key())
    except Exception:
        return False


def _build_prompt(direction: str, asset_symbol: str, timeframe: str, confidence: float,
                   regime: str | None, reasoning_detail: list[dict]) -> str:
    side = "long (BUY)" if direction == "BUY" else "short (SELL)"
    aligned = [r["text"] for r in (reasoning_detail or []) if r.get("aligned")]
    opposing = [r["text"] for r in (reasoning_detail or []) if not r.get("aligned")]
    factors = "; ".join(aligned) or "no single dominant factor"
    counter = ("; ".join(opposing)) if opposing else "none of note"
    return (
        f"You are a concise trading assistant. A rules-based engine already decided the trade "
        f"below by itself -- your only job is to explain it clearly in plain English, not to "
        f"second-guess or change it.\n\n"
        f"Asset: {asset_symbol}\nTimeframe: {timeframe}\nDirection: {side}\n"
        f"Confidence: {confidence:.0f}%\nMarket regime: {regime or 'unknown'}\n"
        f"Supporting factors: {factors}\nOpposing/weaker factors: {counter}\n\n"
        f"Write a 1-2 sentence trader's explanation of why this setup qualifies, in a natural, "
        f"confident but not hyped tone. No disclaimers, no restating these instructions, no "
        f"markdown -- plain text only."
    )


def _call_openai_compatible(base_url: str, api_key: str, model: str, prompt: str) -> str | None:
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
            "max_tokens": 120,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def _call_gemini(base_url: str, api_key: str, model: str, prompt: str) -> str | None:
    resp = requests.post(
        f"{base_url}/models/{model}:generateContent",
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 120},
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def generate_reasoning(direction: str, asset_symbol: str, timeframe: str, confidence: float,
                        regime: str | None, reasoning_detail: list[dict]) -> str | None:
    """Returns an LLM-written narrative, or None if unconfigured / the call
    fails for any reason -- every caller must fall back to the existing
    deterministic reasoning string on None, never surface an error."""
    try:
        cfg = _get_config()
        if not cfg:
            return None
        api_key = cfg.get_api_key()
        if not api_key:
            return None

        provider = cfg.provider
        model = (cfg.config or {}).get("model")
        prompt = _build_prompt(direction, asset_symbol, timeframe, confidence, regime, reasoning_detail)

        if provider == "gemini":
            base_url = cfg.base_url or "https://generativelanguage.googleapis.com/v1beta"
            model = model or "gemini-2.0-flash"
            text = _call_gemini(base_url, api_key, model, prompt)
        else:
            # groq, openrouter, and any other OpenAI-compatible "custom" provider
            base_url = cfg.base_url or "https://api.groq.com/openai/v1"
            model = model or "llama-3.3-70b-versatile"
            text = _call_openai_compatible(base_url, api_key, model, prompt)

        return text[:500] if text else None
    except Exception as e:
        logger.debug(f"LLM reasoning unavailable, falling back to rule-based text: {e}")
        return None
