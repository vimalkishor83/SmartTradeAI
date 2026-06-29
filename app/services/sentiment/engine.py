"""Market sentiment engine combining price trend, RSI, and news sentiment."""


def calculate_sentiment(indicators: dict, news_sentiment: float = 0.0) -> dict:
    score = 50  # neutral baseline

    rsi = indicators.get("rsi") or 50
    macd_hist = indicators.get("macd_hist") or 0
    ema20 = indicators.get("ema20") or 0
    ema50 = indicators.get("ema50") or 0
    supertrend_dir = indicators.get("supertrend_direction", "up")
    cmf = indicators.get("cmf") or 0

    # RSI contribution (-15 to +15)
    if rsi > 70:
        score -= 10
    elif rsi > 55:
        score += 10
    elif rsi < 30:
        score += 15
    elif rsi < 45:
        score -= 10

    # MACD contribution
    if macd_hist > 0:
        score += 10
    elif macd_hist < 0:
        score -= 10

    # Trend
    if ema20 and ema50:
        if ema20 > ema50:
            score += 10
        else:
            score -= 10

    if supertrend_dir == "up":
        score += 5
    else:
        score -= 5

    # Volume/CMF
    if cmf > 0.1:
        score += 5
    elif cmf < -0.1:
        score -= 5

    # News
    score += news_sentiment * 5  # -5 to +5

    score = max(0, min(100, score))

    if score >= 80:
        label = "Very Bullish"
        color = "#00e676"
    elif score >= 60:
        label = "Bullish"
        color = "#76ff03"
    elif score >= 40:
        label = "Neutral"
        color = "#ffeb3b"
    elif score >= 20:
        label = "Bearish"
        color = "#ff7043"
    else:
        label = "Very Bearish"
        color = "#f44336"

    return {"score": round(score, 1), "label": label, "color": color}
