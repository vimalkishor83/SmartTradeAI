"""
Signal generation engine — 7-stage pipeline.

Stage 1: Market session gate      — skip signals outside valid trading hours
Stage 2: Volatility regime gate   — skip if market is too quiet or too chaotic
Stage 3: MTF alignment gate       — higher TF trend must agree with signal direction
Stage 4: Momentum confirmation    — RSI + MACD must support the direction
Stage 5: Volume confirmation      — volume must confirm the move (crypto/stocks only)
Stage 6: Confidence scoring       — multiplicative model, minimum threshold 70
Stage 7: Result packaging         — entry, stop (structure-aware), targets, R:R
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

import pandas as pd

from app.services.indicators.calculator import calculate_all_indicators
from app.services.indicators.patterns import detect_patterns
from app.services.data.quality import assess_data_quality

logger = logging.getLogger(__name__)


# ─── Market session windows (UTC hours) ───────────────────
_SESSIONS = {
    "crypto":        None,                          # 24/7
    "forex":         [(7, 16), (13, 21)],           # London + NY overlap
    "commodity":     [(7, 21)],                     # London open → NY close
    "indian_stock":  [(3, 10)],                     # NSE: 09:15–15:30 IST = 03:45–10:00 UTC
    "index":         [(3, 10)],                     # Same as Indian stocks
}

# Duplicate-signal lockout window per timeframe (minutes)
_LOCKOUT = {
    "1m": 5,  "5m": 20,  "15m": 45,  "30m": 90,
    "1h": 120, "2h": 240, "4h": 480,  "1d": 1440,
}

# Signal expiry per timeframe (minutes)
_EXPIRY = {
    "1m": 5,  "5m": 20,  "15m": 60,  "30m": 120,
    "1h": 240, "2h": 480, "4h": 960,  "1d": 2880,
}

# Minimum candle count required (drives minimum data need)
_MIN_CANDLES = 60


class SignalEngine:

    # ──────────────────────────────────────────────────────
    # Public entry point
    # ──────────────────────────────────────────────────────
    def generate_signal(
        self,
        df: pd.DataFrame,
        asset,
        timeframe: str,
        higher_tf_df: pd.DataFrame | None = None,
        force: bool = False,
        direction_threshold: float = 0.65,
    ) -> dict | None:
        """
        Run the full 7-stage pipeline.
        Returns a signal dict on success, None if any gate rejects.
        `higher_tf_df` is optional OHLCV of the next TF up (for Stage 3).
        `force=True` skips the session gate (used for manual on-demand generation).
        """
        if df is None or len(df) < _MIN_CANDLES:
            return None

        market = getattr(asset, "market", "crypto")

        try:
            # ── Data quality gate ──────────────────────────────────
            # Hard integrity problems (corrupt OHLC, duplicate candles, bad
            # columns) are never OK, live or backtest, so they always block.
            # Staleness is only meaningful for live generation — a backtest
            # deliberately replays historical candles, and comparing their
            # timestamp to wall-clock "now" would flag every single one as
            # stale. Mirrors the existing `if not force` session-gate pattern
            # immediately below so it's bypassed the same way during replay.
            quality = assess_data_quality(df, market, timeframe)
            if quality["hard_invalid"] or (not force and quality["status"] == "RED"):
                logger.warning(
                    "Data quality gate blocked signal for %s %s: %s",
                    getattr(asset, "symbol", "?"), timeframe, quality["issues"],
                )
                return None

            # ── Stage 1: Session gate (skipped for manual/forced generation) ──
            if not force and not self._session_gate(market):
                return None

            # ── Stage 2: Volatility regime gate ───────────────────
            indicators = calculate_all_indicators(df)
            if not indicators:
                return None

            atr      = indicators.get("atr") or 0
            close    = float(df["close"].iloc[-1])
            atr_pct  = (atr / close * 100) if close else 0

            vol_ok, vol_regime = self._volatility_gate(atr_pct)
            if not vol_ok:
                return None

            if not force and not self._trend_strength_gate(indicators.get("adx") or 0):
                return None

            if not force and not self._ema_extension_gate(close, indicators.get("ema9") or 0, atr, timeframe):
                return None

            # ── Stage 3: MTF alignment gate ────────────────────────
            higher_bias = self._mtf_gate(higher_tf_df)
            # higher_bias: "bullish" | "bearish" | "neutral" | None (unknown = skip only if conflict is clear)
            mtf_confirmations = self._mtf_supertrend_confirmation(asset, timeframe)

            # ── Stage 4 & 5: Momentum + Volume pre-scoring ─────────
            # Computed once here and reused at Stage 7 below instead of
            # calling detect_patterns(df) twice on the same unmodified df.
            patterns = detect_patterns(df)
            thresh = 0.55 if force else 0.65
            raw_direction, raw_scores, reasons = self._score_signal(
                indicators, df, market, threshold=thresh, patterns=patterns,
                timeframe=timeframe, mtf_confirmations=mtf_confirmations,
            )

            if raw_direction == "HOLD":
                return None

            # Stage 3 rejection: higher TF clearly disagrees (skipped on force)
            if not force and higher_bias and higher_bias != "neutral":
                if raw_direction == "BUY" and higher_bias == "bearish":
                    return None
                if raw_direction == "SELL" and higher_bias == "bullish":
                    return None

            # Stage 4: Momentum gate (skipped on force)
            if not force and not self._momentum_gate(indicators, raw_direction):
                return None

            if not force and not self._di_direction_gate(
                indicators.get("plus_di") or 0, indicators.get("minus_di") or 0, raw_direction,
            ):
                return None

            # Optional, admin-toggled (default OFF) — see _smc_order_block_gate's
            # own docstring for why these aren't unconditional like the gates
            # above. Two independent toggles, not one combined switch, so
            # either concept can be tested/enabled without the other.
            if not force and self._smc_gate_enabled() and not self._smc_order_block_gate(df, raw_direction, atr):
                return None

            if not force and self._smc_liquidity_enabled() and not self._smc_liquidity_sweep_gate(df, raw_direction, atr):
                return None

            if not force and self._smc_sr_enabled() and not self._smc_support_resistance_gate(df, raw_direction, atr):
                return None

            # Stage 5: Volume gate (skipped on force)
            if not force and market in ("crypto", "indian_stock"):
                if not self._volume_gate(df):
                    return None

            # ── Stage 6: Confidence scoring ────────────────────────
            confidence = self._compute_confidence(raw_scores, higher_bias, raw_direction)
            min_conf = 50 if force else 70

            if confidence < min_conf:
                return None

            # ── Stage 7: Package result (patterns already computed above) ──
            sl       = self._structure_stop(df, raw_direction, close, atr)
            t1, t2, t3 = self._calculate_targets(raw_direction, close, atr)
            rr       = self._risk_reward(close, sl, t1)

            expiry_min = _EXPIRY.get(timeframe, 60)

            structure_level = self._nearest_structure_level(df, raw_direction)
            rsi = indicators.get("rsi") or 50

            return {
                "signal_type":       raw_direction,
                "entry_price":       round(close, 6),
                "stop_loss":         round(sl, 6),
                "target1":           round(t1, 6),
                "target2":           round(t2, 6),
                "target3":           round(t3, 6),
                "risk_reward":       round(rr, 2),
                "confidence_score":  round(confidence, 1),
                "confidence_label":  self._confidence_label(confidence),
                "trend_score":       raw_scores.get("trend", 0),
                "momentum_score":    raw_scores.get("momentum", 0),
                "volume_score":      raw_scores.get("volume", 0),
                "pattern_score":     raw_scores.get("pattern", 0),
                "ai_score":          raw_scores.get("ai", 0),
                "indicators":        indicators,
                "patterns":          patterns,
                "reasoning":         " | ".join(text for _, text, _ in reasons),
                # Structured breakdown so the UI can show which factors
                # actually supported the final direction vs. which were
                # outweighed (e.g. a strong bearish reversal pattern winning
                # out over weaker bullish trend/momentum tags) — the plain
                # `reasoning` string above stays as-is for backward
                # compatibility with anything already reading/persisting it.
                "reasoning_detail":  self._labeled_reasons(reasons, raw_direction),
                "volatility_regime": vol_regime,
                "higher_tf_bias":    higher_bias,
                "regime":            self._regime_label(higher_bias, vol_regime, raw_direction),
                "data_quality":      quality,
                "expires_at":        datetime.utcnow() + timedelta(minutes=expiry_min),
                # ── Deeepr-style position-analysis packaging (additive only —
                # does not affect direction/entry/stop/target math above) ──
                "lane_technical":         self._lane_verdict(
                    raw_scores.get("trend", 0) + raw_scores.get("momentum", 0) + raw_scores.get("pattern", 0),
                    65,  # max trend(30) + momentum(20) + pattern(15)
                    [text for cat, text, _ in reasons if cat in ("trend", "momentum", "pattern")],
                ),
                "lane_flow":              self._lane_verdict(
                    raw_scores.get("volume", 0), 15,
                    [text for cat, text, _ in reasons if cat == "volume"],
                ),
                "invalidation_conditions": self._invalidation_conditions(
                    raw_direction, timeframe, structure_level, rsi, higher_bias,
                ),
                "target_allocations": self._target_allocations(t1, t2, t3),
            }

        except Exception as e:
            logger.error(f"Signal pipeline error [{getattr(asset, 'symbol', '?')}/{timeframe}]: {e}")
            return None

    # ──────────────────────────────────────────────────────
    # Always-on position read (for the UI preview only)
    # ──────────────────────────────────────────────────────
    def analyze(self, df: pd.DataFrame, asset, timeframe: str, higher_tf_df: pd.DataFrame | None = None) -> dict:
        """
        Unlike generate_signal(), this never returns None just because the
        setup isn't strong enough to alert on — it's for the "AI Position
        Analysis" preview panel, which should always show *something*
        (lane scores, reasoning) rather than going blank whenever the
        momentum/volume/MTF gates would have rejected a signal. Those gates
        decide whether to ALERT/persist a signal; they say nothing about
        whether there's a reasonable read to show a user browsing the chart.

        Session/volatility gates still apply — those mean the market is
        genuinely closed or the data is unusable, not just "low conviction".

        Returns {"available": False, "reason": ...} when there's truly
        nothing to show, otherwise a dict shaped like generate_signal()'s
        but with "qualifies_as_signal" and an explicit analysis_state added.
        A usable read is either SIGNAL or NO_SIGNAL; the latter includes a
        reason code/message instead of making HOLD and low-confidence reads
        indistinguishable.
        """
        if df is None or len(df) < _MIN_CANDLES:
            return {
                "available": False,
                "analysis_state": "UNAVAILABLE",
                "reason": "insufficient_data",
            }

        market = getattr(asset, "market", "crypto")

        try:
            if not self._session_gate(market):
                return {
                    "available": False,
                    "analysis_state": "UNAVAILABLE",
                    "reason": "market_closed",
                }

            indicators = calculate_all_indicators(df)
            if not indicators:
                return {
                    "available": False,
                    "analysis_state": "UNAVAILABLE",
                    "reason": "no_indicators",
                }

            atr     = indicators.get("atr") or 0
            close   = float(df["close"].iloc[-1])
            atr_pct = (atr / close * 100) if close else 0

            vol_ok, vol_regime = self._volatility_gate(atr_pct)
            if not vol_ok:
                return {
                    "available": False,
                    "analysis_state": "UNAVAILABLE",
                    "reason": f"volatility_{vol_regime}",
                }

            higher_bias = self._mtf_gate(higher_tf_df)
            mtf_confirmations = self._mtf_supertrend_confirmation(asset, timeframe)
            patterns = detect_patterns(df)
            raw_direction, raw_scores, reasons = self._score_signal(
                indicators, df, market, threshold=0.55, patterns=patterns,
                timeframe=timeframe, mtf_confirmations=mtf_confirmations,
            )

            # Same optional, admin-toggled SMC check as generate_signal() —
            # downgrades to HOLD rather than {"available": False}, since a
            # failed structure check is "no qualifying setup", not "no data",
            # matching this function's own HOLD-producing gates above.
            no_signal_reason = None
            if raw_direction != "HOLD" and self._smc_gate_enabled() and not self._smc_order_block_gate(df, raw_direction, atr):
                raw_direction = "HOLD"
                no_signal_reason = "order_block_not_confirmed"
            if raw_direction != "HOLD" and self._smc_liquidity_enabled() and not self._smc_liquidity_sweep_gate(df, raw_direction, atr):
                raw_direction = "HOLD"
                no_signal_reason = "liquidity_sweep_not_confirmed"
            if raw_direction != "HOLD" and self._smc_sr_enabled() and not self._smc_support_resistance_gate(df, raw_direction, atr):
                raw_direction = "HOLD"
                no_signal_reason = "support_resistance_not_confirmed"

            confidence = (
                self._compute_confidence(raw_scores, higher_bias, raw_direction)
                if raw_direction != "HOLD" else 0.0
            )

            technical = self._lane_verdict(
                raw_scores.get("trend", 0) + raw_scores.get("momentum", 0) + raw_scores.get("pattern", 0),
                65,
                [text for cat, text, _ in reasons if cat in ("trend", "momentum", "pattern")],
            )
            flow = self._lane_verdict(
                raw_scores.get("volume", 0), 15,
                [text for cat, text, _ in reasons if cat == "volume"],
            )

            if raw_direction == "HOLD":
                no_signal_reason = no_signal_reason or "no_clear_direction"
                no_signal_message = {
                    "no_clear_direction": "No clear directional consensus on this timeframe.",
                    "order_block_not_confirmed": "Directional bias exists, but the order-block check is not confirmed.",
                    "liquidity_sweep_not_confirmed": "Directional bias exists, but a confirming liquidity sweep was not found.",
                    "support_resistance_not_confirmed": "Directional bias exists, but nearby support/resistance does not confirm it.",
                }[no_signal_reason]
            elif confidence < 70:
                no_signal_reason = "below_confidence_threshold"
                no_signal_message = (
                    f"Directional bias is present, but confidence is {confidence:.1f}% "
                    "below the 70% auto-alert threshold."
                )
            else:
                no_signal_reason = None
                no_signal_message = None
            qualifies_as_signal = raw_direction != "HOLD" and confidence >= 70

            result = {
                "available":         True,
                "analysis_state":    "SIGNAL" if qualifies_as_signal else "NO_SIGNAL",
                "signal_type":       raw_direction,  # may be "HOLD"
                "confidence_score":  round(confidence, 1),
                "confidence_label":  self._confidence_label(confidence) if raw_direction != "HOLD" else "Neutral",
                "qualifies_as_signal": qualifies_as_signal,
                "no_signal_reason":  no_signal_reason,
                "no_signal_message": no_signal_message,
                "trend_score":       raw_scores.get("trend", 0),
                "momentum_score":    raw_scores.get("momentum", 0),
                "volume_score":      raw_scores.get("volume", 0),
                "pattern_score":     raw_scores.get("pattern", 0),
                "ai_score":          raw_scores.get("ai", 0),
                "lane_technical":    technical,
                "lane_flow":         flow,
                "reasoning":         " | ".join(text for _, text, _ in reasons),
                "reasoning_detail":  self._labeled_reasons(reasons, raw_direction),
                "volatility_regime": vol_regime,
                "higher_tf_bias":    higher_bias,
                "regime":            self._regime_label(higher_bias, vol_regime, raw_direction if raw_direction != "HOLD" else "BUY"),
            }

            if raw_direction != "HOLD":
                sl = self._structure_stop(df, raw_direction, close, atr)
                t1, t2, t3 = self._calculate_targets(raw_direction, close, atr)
                structure_level = self._nearest_structure_level(df, raw_direction)
                rsi = indicators.get("rsi") or 50
                result.update({
                    "entry_price":  round(close, 6),
                    "stop_loss":    round(sl, 6),
                    "target1":      round(t1, 6),
                    "target2":      round(t2, 6),
                    "target3":      round(t3, 6),
                    "risk_reward":  round(self._risk_reward(close, sl, t1), 2),
                    "invalidation_conditions": self._invalidation_conditions(
                        raw_direction, timeframe, structure_level, rsi, higher_bias,
                    ),
                    "target_allocations": self._target_allocations(t1, t2, t3),
                })
            else:
                result.update({
                    "entry_price": None, "stop_loss": None,
                    "target1": None, "target2": None, "target3": None,
                    "risk_reward": 0, "invalidation_conditions": [], "target_allocations": [],
                })

            return result

        except Exception as e:
            logger.error(f"Position analysis error [{getattr(asset, 'symbol', '?')}/{timeframe}]: {e}")
            return {
                "available": False,
                "analysis_state": "UNAVAILABLE",
                "reason": "error",
            }

    # ──────────────────────────────────────────────────────
    # Stage 1 — Market session gate
    # ──────────────────────────────────────────────────────
    def _session_gate(self, market: str) -> bool:
        windows = _SESSIONS.get(market)
        if windows is None:
            return True  # 24/7 market (crypto)
        now_utc = datetime.now(timezone.utc).hour
        return any(start <= now_utc < end for start, end in windows)

    # ──────────────────────────────────────────────────────
    # Combined market-regime label (trend × volatility)
    # ──────────────────────────────────────────────────────
    @staticmethod
    def _regime_label(higher_bias: str | None, vol_regime: str, direction: str) -> str:
        """A discrete regime tag combining macro trend and volatility, e.g.
        'uptrend_normal', 'downtrend_elevated', 'sideways_normal'.

        Trend is taken from the higher-timeframe bias when known, else inferred
        from the signal direction. Additive metadata only — it does not change
        which signals are produced, so it has no effect on win rate."""
        trend = {"bullish": "uptrend", "bearish": "downtrend"}.get(higher_bias or "")
        if trend is None:
            # no higher-TF context — fall back to the signal's own direction
            trend = {"BUY": "uptrend", "SELL": "downtrend"}.get(direction, "sideways")
        vol = vol_regime if vol_regime in ("normal", "elevated") else "normal"
        return f"{trend}_{vol}"

    # ──────────────────────────────────────────────────────
    # Stage 2 — Volatility regime gate
    # ──────────────────────────────────────────────────────
    def _volatility_gate(self, atr_pct: float) -> tuple[bool, str]:
        """
        Returns (allowed, regime_label).
        Too quiet  (<0.1%) → likely consolidation or dead session.
        Too chaotic (>6%)  → news spike, slippage risk too high.
        """
        if atr_pct == 0:
            return True, "unknown"   # no ATR data — allow through (data issue, not a bad market)
        if atr_pct < 0.10:
            return False, "dead"
        if atr_pct > 6.0:
            return False, "chaotic"
        if atr_pct > 3.0:
            return True, "elevated"
        return True, "normal"

    # ADX below this means no clear trend either way — a trend-following
    # signal (this engine's EMA9/21 cross + Supertrend core) has no real
    # edge there, and a live backtest sweep across every currently-active
    # crypto asset showed exactly the signature of trading through that
    # condition anyway: decent-looking win rates (often 45-60%) that still
    # net negative overall, worst on the fastest timeframes (15m/1h) where
    # range-bound chop is most common. 20 is the standard ADX
    # trending/non-trending cutoff (Wilder's own convention), not a value
    # tuned specifically for this data — deliberately rejecting outright
    # rather than just discounting confidence, since a choppy market isn't
    # a weaker version of what this strategy trades, it's the absence of it.
    ADX_TREND_MIN = 20.0

    def _trend_strength_gate(self, adx: float) -> bool:
        if not adx:
            return True  # no ADX data — allow through (data issue, not a bad market)
        return adx >= self.ADX_TREND_MIN

    # Rejects a signal when price has already run too far from its own
    # EMA9 (in ATR terms) before every trend/momentum box happens to tick —
    # e.g. one big impulsive candle satisfies EMA9>EMA21 + Supertrend +
    # MACD all at once, and this engine had nothing checking whether price
    # itself was still near a sane entry, only whether the trend looked
    # right. Two problems compound at that moment: the entry is chasing a
    # move that already happened, and _structure_stop's ATR-based stop is
    # simultaneously WIDER than usual, because the same candle that
    # extended price also just inflated ATR.
    #
    # Live backtest sweep (7-asset active crypto set, 15m/1h/4h, gate off
    # vs. thresholds 1.0/1.5/2.0/2.5x ATR) validated 1.0x specifically on
    # 15m and 1h — 15m avg net -6.43% -> -4.05%, 1h -2.02% -> -0.69% (both
    # also 1.0x's best result; looser thresholds converged back to the
    # gate-off baseline). 4h was WORSE at every threshold tested (net loss
    # increased, profitable-asset count dropped from 2/7 to 0-1/7) — on
    # that timeframe an "extended" candle is more often a genuine,
    # persistent trend worth catching, not a chase, so the gate only
    # applies to 15m/1h (see EMA_EXTENSION_TIMEFRAMES below).
    EMA_EXTENSION_MAX_ATR = 1.0
    EMA_EXTENSION_TIMEFRAMES = ("15m", "1h")

    def _ema_extension_gate(self, close: float, ema9: float, atr: float, timeframe: str) -> bool:
        if timeframe not in self.EMA_EXTENSION_TIMEFRAMES:
            return True
        if not ema9 or not atr:
            return True  # no EMA/ATR data — allow through (data issue, not a bad setup)
        return abs(close - ema9) <= self.EMA_EXTENSION_MAX_ATR * atr

    # ──────────────────────────────────────────────────────
    # Optional SMC (Smart Money Concepts) order-block gate
    # ──────────────────────────────────────────────────────
    # Admin-toggled, default OFF (PlatformConfig.smc_order_block_gate_enabled)
    # — unlike the ADX/DI/EMA-extension gates above, this has NOT yet been
    # through a live-validated backtest sweep proving it improves results,
    # because "where exactly is the order block" is genuinely discretionary
    # in most SMC trading education. Ships as an explicit opt-in so it can
    # be tested against real data before anyone decides it should affect
    # the default signal set. See _smc_order_block_gate for the concrete,
    # deterministic definition actually implemented.
    SMC_SWING_K = 2               # bars each side to confirm a swing pivot
    # Must comfortably fit inside the backtest engine's 60-candle rolling
    # window (warmup=60 in app/services/backtesting/engine.py) or the
    # length guard below fails open on every single call during a
    # backtest, silently testing nothing — found exactly that way: an
    # initial LOOKBACK=60 produced byte-identical gate-on/gate-off results.
    SMC_LOOKBACK = 40             # candles searched for a usable order block
    SMC_IMPULSE_WINDOW = 10       # bars after a swing point to confirm a real impulsive move
    SMC_IMPULSE_ATR_MULT = 2.0    # how big that move must be, in ATR, to count as "impulsive"
    SMC_ZONE_BUFFER_ATR = 0.15    # small tolerance around the zone edges

    def _smc_gate_enabled(self) -> bool:
        try:
            from app.services.platform_config import is_smc_order_block_enabled
            return is_smc_order_block_enabled()
        except Exception:
            return False

    def _smc_liquidity_enabled(self) -> bool:
        try:
            from app.services.platform_config import is_smc_liquidity_sweep_enabled
            return is_smc_liquidity_sweep_enabled()
        except Exception:
            return False

    def _find_swing_points(self, highs, lows, start, end, k):
        """Simple fractal pivots: bar i is a swing high/low if it's the
        max/min among the k bars on each side of it. Returns (swing_high_idx,
        swing_low_idx) lists, indices local to the full series."""
        swing_highs, swing_lows = [], []
        for i in range(max(start, k), min(end, len(highs) - k)):
            window_h = highs[i - k:i + k + 1]
            window_l = lows[i - k:i + k + 1]
            if highs[i] >= window_h.max():
                swing_highs.append(i)
            if lows[i] <= window_l.min():
                swing_lows.append(i)
        return swing_highs, swing_lows

    def _smc_order_block_gate(self, df: pd.DataFrame, direction: str, atr: float) -> bool:
        """True if price is currently sitting inside an unmitigated order
        block in the signal's own direction, OR if there simply isn't
        enough data/no clear structure to judge (fails open — this is a
        quality filter, not a "prove a negative" requirement).

        Definition used (deterministic, not discretionary):
        - A swing low (BUY) / swing high (SELL) followed within
          SMC_IMPULSE_WINDOW bars by a move of at least SMC_IMPULSE_ATR_MULT
          x ATR away from it counts as a confirmed impulsive move.
        - The order block is the last opposite-colored candle at or just
          before that swing point (the last down-candle before a bullish
          impulse, or the last up-candle before a bearish one) — the
          classic SMC "last candle before the move" definition.
        - The zone is that candle's [low, high], with a small ATR buffer.
        - "Unmitigated" means price hasn't closed back through the FAR side
          of the zone (below zone_low for a bullish OB, above zone_high for
          a bearish one) at any point since it formed — that would mean the
          zone already failed, not that it's still a valid area to react
          from.
        - The gate passes if the CURRENT close sits inside (or just
          outside, within the buffer of) any such still-valid zone.
        """
        if not atr or len(df) < self.SMC_LOOKBACK + self.SMC_SWING_K + 1:
            return True

        highs  = df["high"].astype(float).reset_index(drop=True)
        lows   = df["low"].astype(float).reset_index(drop=True)
        opens  = df["open"].astype(float).reset_index(drop=True)
        closes = df["close"].astype(float).reset_index(drop=True)
        n = len(df)
        start = max(0, n - self.SMC_LOOKBACK)
        k = self.SMC_SWING_K

        swing_highs, swing_lows = self._find_swing_points(highs.values, lows.values, start, n, k)
        current_close = float(closes.iloc[-1])
        buffer = self.SMC_ZONE_BUFFER_ATR * atr
        pivots = swing_lows if direction == "BUY" else swing_highs

        for p_idx in pivots:
            window_end = min(n, p_idx + self.SMC_IMPULSE_WINDOW)
            if window_end <= p_idx:
                continue
            pivot_price = float(lows.iloc[p_idx]) if direction == "BUY" else float(highs.iloc[p_idx])
            if direction == "BUY":
                extreme = float(highs.iloc[p_idx:window_end].max())
                impulsive = (extreme - pivot_price) >= self.SMC_IMPULSE_ATR_MULT * atr
            else:
                extreme = float(lows.iloc[p_idx:window_end].min())
                impulsive = (pivot_price - extreme) >= self.SMC_IMPULSE_ATR_MULT * atr
            if not impulsive:
                continue

            # Walk back a few bars from the pivot to find the last
            # opposite-colored candle — the order block itself.
            ob_idx = None
            for j in range(p_idx, max(start, p_idx - k - 2), -1):
                is_down = closes.iloc[j] < opens.iloc[j]
                is_up   = closes.iloc[j] > opens.iloc[j]
                if direction == "BUY" and is_down:
                    ob_idx = j
                    break
                if direction == "SELL" and is_up:
                    ob_idx = j
                    break
            if ob_idx is None:
                continue

            zone_low  = float(lows.iloc[ob_idx])
            zone_high = float(highs.iloc[ob_idx])

            # Invalidated if price already closed through the far side
            # anywhere between the OB forming and now.
            after = closes.iloc[ob_idx + 1:n]
            if direction == "BUY" and (after < zone_low - buffer).any():
                continue
            if direction == "SELL" and (after > zone_high + buffer).any():
                continue

            if (zone_low - buffer) <= current_close <= (zone_high + buffer):
                return True

        return False

    # Separate toggle from the order-block gate (PlatformConfig.
    # smc_liquidity_sweep_gate_enabled) so the two can be tested
    # independently rather than forced to move together. "Liquidity" here
    # means the same thing app/api/v1/market_data.py's _compute_liquidity
    # already displays on the Advanced Analysis chart (a cluster of stops
    # sitting just past an obvious swing high/low) — this gate doesn't
    # call that function directly (it clusters MULTIPLE nearby pivots for
    # a chart overlay; a single genuine pivot is enough to confirm a real
    # sweep for a gating decision), but it's the same underlying concept,
    # confirmed to already have a real, working implementation elsewhere
    # in this codebase before writing a second one here.
    SMC_SWEEP_REBOUND_ATR = 0.1   # how far back above/below the pivot counts as "reclaimed"

    def _smc_liquidity_sweep_gate(self, df: pd.DataFrame, direction: str, atr: float) -> bool:
        """True if price recently swept a swing low (BUY) / swing high
        (SELL) -- traded through it, taking out the stops sitting just
        beyond it -- and then reclaimed back the other side, which is the
        classic SMC "stop hunt then reverse" confirmation. Fails open (True)
        on insufficient data, same convention as the order-block gate."""
        if not atr or len(df) < self.SMC_LOOKBACK + self.SMC_SWING_K + 1:
            return True

        highs  = df["high"].astype(float).reset_index(drop=True)
        lows   = df["low"].astype(float).reset_index(drop=True)
        closes = df["close"].astype(float).reset_index(drop=True)
        n = len(df)
        start = max(0, n - self.SMC_LOOKBACK)
        k = self.SMC_SWING_K

        swing_highs, swing_lows = self._find_swing_points(highs.values, lows.values, start, n, k)
        current_close = float(closes.iloc[-1])
        rebound = self.SMC_SWEEP_REBOUND_ATR * atr
        pivots = swing_lows if direction == "BUY" else swing_highs

        for p_idx in pivots:
            if p_idx >= n - 1:
                continue  # need at least one bar after the pivot to have swept it
            pivot_price = float(lows.iloc[p_idx]) if direction == "BUY" else float(highs.iloc[p_idx])
            after_low  = lows.iloc[p_idx + 1:n]
            after_high = highs.iloc[p_idx + 1:n]

            if direction == "BUY":
                swept = (after_low < pivot_price).any()
                reclaimed = current_close > pivot_price + rebound
            else:
                swept = (after_high > pivot_price).any()
                reclaimed = current_close < pivot_price - rebound

            if swept and reclaimed:
                return True

        return False

    # Third and last of the concepts named in the original request (order
    # blocks, liquidity, support/resistance) — its own independent toggle,
    # same off-by-default/not-yet-multi-asset-validated status as the two
    # above. Unlike those two (built around a SINGLE swing point), proper
    # S/R needs multiple nearby pivots clustered into a zone and a real
    # touch count — the same clustering shape as _compute_liquidity in
    # app/api/v1/market_data.py (found during the fake-data sweep), applied
    # here as a gate rather than a chart overlay. A longer lookback than
    # the order-block/liquidity gates on purpose: a level only a handful of
    # candles old isn't "support/resistance" in any meaningful sense yet,
    # it's just the last swing point — real S/R needs more history to have
    # actually been tested more than once. Still small enough to fit the
    # backtest engine's 60-candle rolling window (see SMC_LOOKBACK's own
    # comment for why that ceiling matters).
    SMC_SR_LOOKBACK = 55
    SMC_SR_MIN_TOUCHES = 2          # how many distinct pivots must cluster together to count as a real zone
    SMC_SR_CLUSTER_TOLERANCE_PCT = 0.003   # 0.3% -- how close two pivots must be to count as "the same level"
    SMC_SR_ZONE_BUFFER_ATR = 0.3    # wider than the order-block buffer -- S/R is a zone, not a precise line

    def _smc_sr_enabled(self) -> bool:
        try:
            from app.services.platform_config import is_smc_support_resistance_enabled
            return is_smc_support_resistance_enabled()
        except Exception:
            return False

    def _cluster_pivot_prices(self, prices: list[float]) -> list[tuple[float, int]]:
        """Groups nearby prices (within SMC_SR_CLUSTER_TOLERANCE_PCT of each
        other) into zones, same tolerance-clustering shape as
        _compute_liquidity in app/api/v1/market_data.py. Returns
        (zone_price, touch_count) for zones with enough touches."""
        clusters: list[list[float]] = []
        for p in prices:
            if p <= 0:
                continue
            placed = False
            for c in clusters:
                ref = sum(c) / len(c)
                if abs(p - ref) / ref <= self.SMC_SR_CLUSTER_TOLERANCE_PCT:
                    c.append(p)
                    placed = True
                    break
            if not placed:
                clusters.append([p])
        return [(sum(c) / len(c), len(c)) for c in clusters if len(c) >= self.SMC_SR_MIN_TOUCHES]

    def _smc_support_resistance_gate(self, df: pd.DataFrame, direction: str, atr: float) -> bool:
        """True if price is currently near a real, multiple-times-tested
        support zone (BUY) or resistance zone (SELL) — clustered swing
        pivots with at least SMC_SR_MIN_TOUCHES hits, not just the single
        most recent swing point. Fails open on insufficient data, same
        convention as the other two SMC gates."""
        if not atr or len(df) < self.SMC_SR_LOOKBACK + self.SMC_SWING_K + 1:
            return True

        highs = df["high"].astype(float).reset_index(drop=True)
        lows  = df["low"].astype(float).reset_index(drop=True)
        closes = df["close"].astype(float).reset_index(drop=True)
        n = len(df)
        start = max(0, n - self.SMC_SR_LOOKBACK)
        k = self.SMC_SWING_K

        swing_highs, swing_lows = self._find_swing_points(highs.values, lows.values, start, n, k)
        current_close = float(closes.iloc[-1])
        buffer = self.SMC_SR_ZONE_BUFFER_ATR * atr

        if direction == "BUY":
            pivot_prices = [float(lows.iloc[i]) for i in swing_lows]
        else:
            pivot_prices = [float(highs.iloc[i]) for i in swing_highs]

        zones = self._cluster_pivot_prices(pivot_prices)
        return any(abs(current_close - zone_price) <= buffer for zone_price, _hits in zones)

    # ──────────────────────────────────────────────────────
    # Stage 3 — Higher timeframe alignment gate
    # ──────────────────────────────────────────────────────
    def _mtf_gate(self, higher_df: pd.DataFrame | None) -> str | None:
        """Return 'bullish', 'bearish', or 'neutral' from the higher TF, or None if unavailable."""
        if higher_df is None or len(higher_df) < 30:
            return None
        try:
            ind = calculate_all_indicators(higher_df)
            ema9 = ind.get("ema9") or 0
            ema21 = ind.get("ema21") or 0
            supertrend = ind.get("supertrend_direction", "up")
            close = float(higher_df["close"].iloc[-1])

            bull_votes = 0
            bear_votes = 0
            if ema9 and ema21:
                if ema9 > ema21: bull_votes += 1
                else:            bear_votes += 1
            if supertrend == "up":   bull_votes += 1
            else:                    bear_votes += 1
            if ema9 and close > ema9: bull_votes += 1
            else:                     bear_votes += 1

            if bull_votes >= 2: return "bullish"
            if bear_votes >= 2: return "bearish"
            return "neutral"
        except Exception:
            return None

    # ──────────────────────────────────────────────────────
    # Stage 3b — 15m/1h Supertrend confirmation (1m/5m/15m signals only)
    # ──────────────────────────────────────────────────────
    _MTF_CONFIRM_TFS = ("15m", "1h")

    def _mtf_supertrend_confirmation(self, asset, timeframe: str) -> list[tuple[str, str]]:
        """For a signal on 1m, 5m, or 15m, pulls Supertrend direction on
        15m and 1h too (whichever isn't `timeframe` itself, to avoid
        re-reading the signal's own timeframe as if it were a second,
        independent confirmation) — a genuine "does the bigger picture
        agree" check for the timeframes fast enough to whipsaw on their
        own. Returns a list of (tf_label, "up"/"down"); _score_signal
        turns each into both a trend_bull/trend_bear contribution
        (moving confidence) and a labeled "Why" reason. Best-effort: a
        fetch failure for one or both confirmation timeframes just means
        fewer confirmations, never blocks the signal itself.
        """
        if timeframe not in ("1m", "5m", "15m"):
            return []
        confirmations = []
        try:
            from app.services.data.fetcher import market_fetcher
            for tf in self._MTF_CONFIRM_TFS:
                if tf == timeframe:
                    continue
                try:
                    confirm_df = market_fetcher.fetch(asset, tf, 220)
                    if confirm_df is None or len(confirm_df) < 30:
                        continue
                    ind = calculate_all_indicators(confirm_df, light=True)
                    direction = ind.get("supertrend_direction")
                    if direction:
                        confirmations.append((tf, direction))
                except Exception:
                    continue
        except Exception:
            pass
        return confirmations

    # ──────────────────────────────────────────────────────
    # Stage 4 — Momentum gate
    # ──────────────────────────────────────────────────────
    def _momentum_gate(self, ind: dict, direction: str) -> bool:
        """
        BUY signals must not have overbought RSI.
        SELL signals must not have oversold RSI.
        MACD histogram must agree.
        Both conditions must be met.
        """
        rsi  = ind.get("rsi") or 50
        macd_hist = ind.get("macd_hist") or 0

        if direction == "BUY":
            rsi_ok  = rsi < 75         # not extreme overbought
            macd_ok = macd_hist >= 0   # histogram not deeply negative
        else:
            rsi_ok  = rsi > 25         # not extreme oversold
            macd_ok = macd_hist <= 0

        return rsi_ok and macd_ok

    def _di_direction_gate(self, plus_di: float, minus_di: float, direction: str) -> bool:
        """+DI/-DI (Wilder's directional movement lines) must agree with the
        signal's direction. ADX (the trend-strength gate above) only says a
        trend exists, not which way — this is the direction check that
        pairs with it, and it's a genuinely different read than the EMA9/21
        cross that mostly drives `trend_bull`/`trend_bear`: DI is derived
        from expanding highs/lows, not moving-average position, so it can
        disagree with the EMA cross right at a stalling/reversing move."""
        if not plus_di or not minus_di:
            return True  # no DI data — allow through (data issue, not a bad market)
        if direction == "BUY":
            return plus_di > minus_di
        return minus_di > plus_di

    # ──────────────────────────────────────────────────────
    # Stage 5 — Volume gate
    # ──────────────────────────────────────────────────────
    def _volume_gate(self, df: pd.DataFrame) -> bool:
        """Volume on signal candle must be ≥ 0.8× 20-period average (relaxed to avoid over-filtering)."""
        if "volume" not in df.columns:
            return True
        avg_vol  = df["volume"].rolling(20).mean().iloc[-1]
        curr_vol = df["volume"].iloc[-1]
        if not avg_vol or avg_vol == 0:
            return True
        return curr_vol >= avg_vol * 0.8

    # ──────────────────────────────────────────────────────
    # Stage 6 — Confidence scoring (multiplicative)
    # ──────────────────────────────────────────────────────
    def _score_signal(self, ind: dict, df: pd.DataFrame, market: str, threshold: float = 0.65, patterns=None,
                       timeframe: str = "", mtf_confirmations: list[tuple[str, str]] | None = None):
        """
        Compute raw direction, per-component scores, and reasons.
        Returns (direction, scores_dict, reasons_list).

        `patterns` may be pre-computed and passed in by the caller (Stage 7
        needs detect_patterns(df) again for the packaged result) to avoid
        running the same O(n) pattern scan over the same unmodified df
        twice per generate_signal() call — this runs for every asset x
        timeframe combination in every scan/prewarm cycle, so the duplicate
        scan was pure wasted work at scale.

        `timeframe` gates two 1m/5m/15m-only additions: an EMA50 read
        (`timeframe` in ("1m","5m")) and `mtf_confirmations` — a list of
        (tf_label, "up"/"down") Supertrend readings from 15m/1h, pre-fetched
        by the caller via _mtf_supertrend_confirmation() for `timeframe` in
        ("1m","5m","15m"). See their use below for what each does to
        scoring vs. just display.
        """
        bull = 0
        bear = 0
        # Each entry is (category, text) — category drives which lane
        # (technical/flow) a reason is grouped under in _lane_verdicts().
        reasons = []
        # Automatic signals do not invoke the ML predictor. Keep the legacy
        # field at zero rather than awarding a fabricated confidence bonus;
        # the manual admin path adds a real AI score only after prediction.
        scores = {"trend": 0, "momentum": 0, "volume": 0, "pattern": 0, "ai": 0}

        close    = float(df["close"].iloc[-1])
        ema9     = ind.get("ema9") or 0
        ema21    = ind.get("ema21") or 0
        ema50    = ind.get("ema50") or 0
        ema100   = ind.get("ema100") or 0
        ema200   = ind.get("ema200") or 0
        vwap     = ind.get("vwap") or 0
        supertrend_dir = ind.get("supertrend_direction", "up")
        ichi_a   = ind.get("ichimoku_senkou_a") or 0
        ichi_b   = ind.get("ichimoku_senkou_b") or 0
        rsi      = ind.get("rsi") or 50
        macd     = ind.get("macd") or 0
        macd_sig = ind.get("macd_signal") or 0
        macd_hist= ind.get("macd_hist") or 0

        # ── Trend component (up to 30 pts) ────────────────
        trend_bull = 0
        trend_bear = 0

        if ema9 and ema21:
            if ema9 > ema21:
                trend_bull += 8; reasons.append(("trend", "EMA9>EMA21 (uptrend)", "bull"))
            else:
                trend_bear += 8; reasons.append(("trend", "EMA9<EMA21 (downtrend)", "bear"))

        if ema50 and ema200:
            if ema50 > ema200:
                trend_bull += 5; reasons.append(("trend", "Golden cross zone", "bull"))
            else:
                trend_bear += 5; reasons.append(("trend", "Death cross zone", "bear"))

        if vwap and close:
            if close > vwap:
                trend_bull += 6; reasons.append(("trend", "Price above VWAP", "bull"))
            else:
                trend_bear += 6

        if supertrend_dir == "up":
            trend_bull += 7; reasons.append(("trend", "SuperTrend bullish", "bull"))
        else:
            trend_bear += 7; reasons.append(("trend", "SuperTrend bearish", "bear"))

        if ichi_a and ichi_b and close:
            cloud_top = max(ichi_a, ichi_b)
            cloud_bot = min(ichi_a, ichi_b)
            if close > cloud_top:
                trend_bull += 4; reasons.append(("trend", "Price above Ichimoku cloud", "bull"))
            elif close < cloud_bot:
                trend_bear += 4

        # EMA50 read for the fast timeframes — shown in "Why" for extra
        # context on 1m/5m (where EMA9/21 alone whips around a lot), but
        # deliberately doesn't add to trend_bull/trend_bear: analysis only,
        # not a confidence input, unlike the MTF Supertrend check below.
        if timeframe in ("1m", "5m") and ema50 and close:
            if close > ema50:
                reasons.append(("trend", "Price above EMA50 (1m/5m)", "bull"))
            else:
                reasons.append(("trend", "Price below EMA50 (1m/5m)", "bear"))

        # Multi-timeframe Supertrend confirmation — for 1m/5m/15m signals,
        # 15m and 1h Supertrend direction (whichever isn't this signal's
        # own timeframe, to avoid double-counting the "SuperTrend
        # bullish/bearish" reason above) genuinely moves trend_bull/
        # trend_bear, so a higher timeframe agreeing lifts confidence and
        # one disagreeing pulls it down — not just informational.
        for tf_label, direction in (mtf_confirmations or []):
            if direction == "up":
                trend_bull += 5; reasons.append(("trend", f"{tf_label} SuperTrend bullish (MTF)", "bull"))
            else:
                trend_bear += 5; reasons.append(("trend", f"{tf_label} SuperTrend bearish (MTF)", "bear"))

        trend_total = trend_bull + trend_bear
        if trend_total > 0:
            scores["trend"] = round((trend_bull / trend_total) * 30)
            bull += trend_bull
            bear += trend_bear

        # ── Momentum component (up to 20 pts) ─────────────
        mom_bull = 0
        mom_bear = 0

        # RSI prime zones give most conviction
        if 40 <= rsi <= 60:
            pass
        elif 30 <= rsi < 40:
            mom_bull += 6; reasons.append(("momentum", f"RSI recovering from oversold ({rsi:.0f})", "bull"))
        elif rsi < 30:
            mom_bull += 10; reasons.append(("momentum", f"RSI oversold ({rsi:.0f})", "bull"))
        elif 60 < rsi <= 70:
            mom_bull += 4; reasons.append(("momentum", f"RSI bullish zone ({rsi:.0f})", "bull"))
        elif rsi > 70:
            mom_bear += 8; reasons.append(("momentum", f"RSI overbought ({rsi:.0f})", "bear"))

        if macd > macd_sig and macd_hist > 0:
            mom_bull += 10; reasons.append(("momentum", "MACD bullish crossover", "bull"))
        elif macd < macd_sig and macd_hist < 0:
            mom_bear += 10; reasons.append(("momentum", "MACD bearish crossover", "bear"))
        elif macd_hist > 0:
            mom_bull += 4
        elif macd_hist < 0:
            mom_bear += 4

        mom_total = mom_bull + mom_bear
        if mom_total > 0:
            scores["momentum"] = round((max(mom_bull, mom_bear) / mom_total) * 20)
            bull += mom_bull
            bear += mom_bear

        # ── Volume component (up to 15 pts) ───────────────
        if "volume" in df.columns and market in ("crypto", "indian_stock"):
            avg_vol  = df["volume"].rolling(20).mean().iloc[-1]
            curr_vol = df["volume"].iloc[-1]
            if avg_vol and avg_vol > 0:
                vol_ratio = curr_vol / avg_vol
                # Volume reasons describe conviction/quality, not direction —
                # tagged "neutral" rather than bull/bear.
                if vol_ratio >= 2.0:
                    scores["volume"] = 15; reasons.append(("volume", "Strong volume spike (2×+)", "neutral"))
                elif vol_ratio >= 1.5:
                    scores["volume"] = 10; reasons.append(("volume", "Volume spike (1.5×+)", "neutral"))
                elif vol_ratio >= 1.0:
                    scores["volume"] = 6; reasons.append(("volume", "Volume in line with average", "neutral"))
                else:
                    scores["volume"] = 2  # low volume — weak signal
                    reasons.append(("volume", "Below-average volume", "neutral"))

        # ── Pattern component (up to 15 pts) ──────────────
        try:
            if patterns is None:
                patterns = detect_patterns(df)
            bull_pat = [p for p in patterns if p["type"] == "bullish"]
            bear_pat = [p for p in patterns if p["type"] == "bearish"]
            if bull_pat:
                best = max(bull_pat, key=lambda p: p["strength"])
                scores["pattern"] = min(15, int(best["strength"] / 7))
                reasons.append(("pattern", f"Pattern: {best['name']}", "bull"))
                bull += best["strength"]
            elif bear_pat:
                best = max(bear_pat, key=lambda p: p["strength"])
                scores["pattern"] = min(15, int(best["strength"] / 7))
                reasons.append(("pattern", f"Pattern: {best['name']}", "bear"))
                bear += best["strength"]
        except Exception:
            pass

        # Direction decision
        total = bull + bear
        if total == 0:
            direction = "HOLD"
        elif bull / total >= threshold:
            direction = "BUY"
        elif bear / total >= threshold:
            direction = "SELL"
        else:
            direction = "HOLD"

        return direction, scores, reasons

    def _compute_confidence(self, scores: dict, higher_bias: str | None, direction: str) -> float:
        """
        Multiplicative confidence model.
        Base = sum of component scores.
        Applied multipliers: trend alignment, MTF agreement.
        """
        base = sum(scores.values())   # max ~100

        # Trend alignment multiplier. MAX_TREND_SCORE (30) matches the cap
        # applied when "trend" is first computed (round(... * 30) above).
        MAX_TREND_SCORE = 30
        trend_pct = scores.get("trend", 0) / MAX_TREND_SCORE
        if trend_pct >= 0.80:
            trend_mult = 1.15
        elif trend_pct >= 0.60:
            trend_mult = 1.05
        elif trend_pct >= 0.40:
            trend_mult = 0.95
        else:
            trend_mult = 0.80

        # MTF alignment multiplier
        if higher_bias is None or higher_bias == "neutral":
            mtf_mult = 1.0
        elif (direction == "BUY" and higher_bias == "bullish") or \
             (direction == "SELL" and higher_bias == "bearish"):
            mtf_mult = 1.15   # agreement boost
        else:
            mtf_mult = 0.85   # mild disagreement (hard disagreement blocked in Stage 3)

        # Volume confirmation multiplier
        vol_score = scores.get("volume", 0)
        if vol_score >= 10:
            vol_mult = 1.05
        elif vol_score == 0:
            vol_mult = 0.95
        else:
            vol_mult = 1.0

        confidence = base * trend_mult * mtf_mult * vol_mult
        return min(100.0, round(confidence, 1))

    # ──────────────────────────────────────────────────────
    # Stage 7 helpers
    # ──────────────────────────────────────────────────────
    def _structure_stop(self, df: pd.DataFrame, direction: str, close: float, atr: float) -> float:
        """
        Structure-aware stop-loss: use recent swing high/low where possible,
        fall back to ATR-based stop. Take whichever is tighter (less risk).
        """
        lookback = df.tail(10)
        atr_sl   = atr if atr else close * 0.01

        # Stop at 1.8×ATR (wider than the 1.2×ATR target — see _calculate_targets)
        # so noise doesn't stop trades out prematurely. Backtest across BTC/SOL/ETH
        # showed this T1/SL pairing lifts win rate ~34% -> ~60% while staying
        # profitable (avg R positive), vs a symmetric 1.5/1.5 that loses money.
        if direction == "BUY":
            structure_sl  = float(lookback["low"].min()) * 0.9995
            atr_based_sl  = close - 1.8 * atr_sl
            stop          = max(structure_sl, atr_based_sl)   # higher = tighter for a long
        else:
            structure_sl  = float(lookback["high"].max()) * 1.0005
            atr_based_sl  = close + 1.8 * atr_sl
            stop          = min(structure_sl, atr_based_sl)   # lower = tighter for a short

        # Enforce minimum stop distance = 0.3× ATR to avoid stop-hunting
        min_dist = atr_sl * 0.3
        if direction == "BUY" and (close - stop) < min_dist:
            stop = close - min_dist
        elif direction == "SELL" and (stop - close) < min_dist:
            stop = close + min_dist

        return round(stop, 8)

    def _nearest_structure_level(self, df: pd.DataFrame, direction: str) -> float:
        """Raw recent swing low/high (no safety buffer) — the 'nearest support/
        resistance' a soft invalidation condition is framed against, as
        distinct from the actual (buffered) stop-loss from _structure_stop."""
        lookback = df.tail(10)
        if direction == "BUY":
            return float(lookback["low"].min())
        return float(lookback["high"].max())

    def _invalidation_conditions(
        self, direction: str, timeframe: str, structure_level: float,
        rsi: float, higher_bias: str | None,
    ) -> list[str]:
        """Plain-language conditions that would invalidate this signal's thesis,
        built entirely from data already computed in this pipeline run."""
        conditions = []
        level = round(structure_level, 6)
        if direction == "BUY":
            conditions.append(f"{timeframe} close below {level} (nearest support)")
            conditions.append(f"RSI drops below 40 on {timeframe}" if rsi >= 40
                               else f"RSI fails to reclaim 40 on {timeframe}")
            if higher_bias == "bullish":
                conditions.append("Higher-timeframe bias flips bearish")
        else:
            conditions.append(f"{timeframe} close above {level} (nearest resistance)")
            conditions.append(f"RSI rises above 60 on {timeframe}" if rsi <= 60
                               else f"RSI fails to reject below 60 on {timeframe}")
            if higher_bias == "bearish":
                conditions.append("Higher-timeframe bias flips bullish")
        return conditions

    def _target_allocations(self, t1: float, t2: float, t3: float) -> list[dict]:
        """Suggested partial-profit split across the three targets — 50/30/20
        is a common runner-friendly scheme. Presentational only; does not
        change what the targets are or how they're simulated in backtests."""
        return [
            {"level": "T1", "price": round(t1, 6), "pct": 50},
            {"level": "T2", "price": round(t2, 6), "pct": 30},
            {"level": "T3", "price": round(t3, 6), "pct": 20},
        ]

    @staticmethod
    def _lane_verdict(score: float, max_score: float, reasons: list[str]) -> dict:
        """Package a raw component score into a Deeepr-style lane verdict:
        a 0-100 strength, a coarse LOW/MODERATE/HIGH label, and up to 3
        supporting reasons."""
        pct = (score / max_score) if max_score else 0.0
        if pct >= 0.7:
            verdict = "HIGH"
        elif pct >= 0.4:
            verdict = "MODERATE"
        else:
            verdict = "LOW"
        return {
            "score": round(pct * 100),
            "verdict": verdict,
            "reasons": reasons[:3] or ["No strong signal from this factor"],
        }

    @staticmethod
    def _labeled_reasons(reasons: list[tuple[str, str, str]], direction: str) -> list[dict]:
        """Marks each scored factor as `aligned` (supports the final BUY/SELL
        direction) or not (outweighed by stronger opposing factors — most
        often a single high-strength reversal pattern beating several
        smaller trend/momentum tags pointing the other way). Without this,
        the UI's flat reasoning list reads as self-contradictory whenever
        that override happens — e.g. a SELL signal listing "SuperTrend
        bullish" with no indication it lost the vote. Volume reasons are
        quality/conviction signals, not directional ones, so they're always
        aligned rather than compared against `direction`."""
        target_lean = "bull" if direction == "BUY" else "bear" if direction == "SELL" else None
        return [
            {"text": text, "lean": lean, "aligned": lean == "neutral" or lean == target_lean}
            for _, text, lean in reasons
        ]

    def _calculate_targets(self, direction: str, price: float, atr: float) -> tuple[float, float, float]:
        # T1 at 1.2×ATR (closer than the 1.8×ATR stop) so it is reached far more
        # often — this is what lifts the win rate. T2/T3 stay extended for
        # runners. Pairing validated by the walk-forward backtest.
        atr = atr or price * 0.01
        if direction == "BUY":
            return price + 1.2 * atr, price + 2.5 * atr, price + 4.0 * atr
        elif direction == "SELL":
            return price - 1.2 * atr, price - 2.5 * atr, price - 4.0 * atr
        else:
            return price + atr, price + 1.5 * atr, price + 2.5 * atr

    def _risk_reward(self, entry: float, sl: float, t1: float) -> float:
        risk   = abs(entry - sl)
        reward = abs(t1 - entry)
        return round(reward / risk, 2) if risk > 0 else 0

    def _confidence_label(self, score: float) -> str:
        if score >= 90: return "Very Strong"
        if score >= 80: return "Strong"
        if score >= 70: return "Moderate"
        return "Weak"

    # ──────────────────────────────────────────────────────
    # Utility: lockout window per timeframe
    # ──────────────────────────────────────────────────────
    @staticmethod
    def lockout_minutes(timeframe: str) -> int:
        return _LOCKOUT.get(timeframe, 30)


signal_engine = SignalEngine()
