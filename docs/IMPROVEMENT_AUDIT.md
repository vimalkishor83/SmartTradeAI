# SmartTrade AI — Improvement Audit

**Status:** Living document. Started as Phase 0 of a structured production-hardening pass; updated as each subsequent phase's investigation and fixes land. Every entry below is based on reading the actual code and, where marked, verifying behavior live on the production server — not on the platform's design intent or documentation claims.

**Last updated:** 2026-09-05 (Phase 0 + Phase 1 + Phase 2 + Phase 3 + Phase 4 + Phase 5 initial pass)

Phase 0 architecture and sequencing artifacts are maintained in [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) and [`docs/ENTERPRISE_TRANSFORMATION_PLAN.md`](ENTERPRISE_TRANSFORMATION_PLAN.md). They describe the current implementation and do not imply that planned AI, calibration, observability or frontend capabilities already exist.

---

## 1. Current Architecture (as verified)

| Layer | Implementation |
|---|---|
| Backend framework | Flask, gunicorn + eventlet worker class |
| Database | PostgreSQL (SQLAlchemy ORM), Alembic migrations |
| Cache / rate-limit store | Redis (Flask-Caching + Flask-Limiter), falls back to in-memory `SimpleCache`/`memory://` if `REDIS_URL` unset |
| Background jobs | APScheduler, split across two processes via `RUN_SCHEDULER` env var — `app` (web, `RUN_SCHEDULER=0`) and `worker` (`RUN_SCHEDULER=1`) are separate Docker containers with independent filesystems and in-memory state |
| Real-time | Flask-SocketIO (WebSocket) for authenticated live dashboard pushes; Delta Exchange WS stream feeds an in-memory live-price cache for crypto |
| Auth | Flask-JWT-Extended (access + refresh tokens, header **and** cookie transport, CSRF-protected cookies), bcrypt password hashing |
| RBAC | `Role` (name-based: admin/premium/pro/basic/free) + a separate `is_super_admin` boolean gate on top of the admin role for destructive admin actions; tier/feature gating is separately driven by `Subscription` (`tier_level`, per-feature boolean flags like `backtesting_enabled`) — role and subscription are deliberately independent axes, not one hierarchy |
| Market data | `market_fetcher` (`app/services/data/fetcher.py`) — Delta Exchange (crypto, WS-first with 15s-stale REST fallback), Binance (crypto fallback), Yahoo Finance (forex/stocks/indices/commodities, 5s in-memory `_ticker_cache` to collapse redundant calls across independent call sites) |
| Indicators | `app/services/indicators/` — `calculator.py` (~23 core values: EMA9/20/21/50/100/200, SMA20/50, RSI, MACD+signal+hist, Stoch RSI K/D, CCI, ROC, Bollinger upper/mid/lower/width, CMF, plus a "light" vs full mode; full mode adds VWAP, Ichimoku senkou A/B, ATR, Keltner upper/lower, ADX, +DI/-DI = ~35 total), `patterns.py` (candlestick pattern detection), `ema_mtf.py` (multi-timeframe EMA9/21 alignment) |
| Signal generation | `app/services/signals/engine.py` (`signal_engine.generate_signal`) — trend/momentum/volume/MTF-alignment checks + ML confidence score; has a `force=True` bypass of the live session-time gate used specifically so backtesting can replay historical bars |
| ML models | Random Forest, XGBoost, LightGBM, LSTM (per prior session context — not re-verified in this pass; see Phase 2 for a dedicated audit) |
| **Backtesting — two separate engines** | **(1)** `app/services/backtest/runner.py` — "walk-forward" engine, replays history through the *live* `signal_engine` bar-by-bar (`window = df.iloc[:i+1]`, forward sim only on `df.iloc[i+1:]` — look-ahead-safe by construction), exposed as `GET /api/v1/signals/backtest` ("Live Engine" in the UI). **(2)** `app/services/backtesting/engine.py` — a separate, older engine that backtests a *named strategy config* (EMA Crossover, RSI+MACD, SuperTrend, etc.) against stored parameters, exposed as `POST /api/v1/backtesting/run`. These are genuinely different systems with different response schemas (`sample_trades` vs `trades_data`, `win_rate`/`raw_win_rate` vs `win_rate` alone) — see §3 for a bug this caused. |
| Notifications | In-app (`Notification` model) + WebSocket push + Telegram (per-user personal bot/chat, `TelegramAlertChannel` group broadcasts, and a separate `PlatformConfig.telegram_security_chat_id` stream for security events — new-IP login, failed login, admin-unauthorized access, anonymous visits) + browser push (`push_subscription`) |
| Logging | Standard `logging` module; `AuditLog` model for admin/security-relevant actions, gated by `PlatformConfig.audit_log_super_admins` (off by default for super-admin's own actions) |
| Frontend | Server-rendered Jinja2 templates + vanilla JS (no SPA framework, no frontend build/test pipeline) for the dashboard app; the 5 in-scope public pages (`/home`, `/login`, `/register`, `/forgot-password`, plus the legal-doc pages) are standalone static HTML with their own inlined CSS/JS, deliberately not sharing `partials/base.html`'s dashboard shell |
| Testing | pytest, `tests/unit/` + `tests/integration/`, runs against `TestingConfig` (`sqlite:///:memory:`), scheduler disabled. 118 tests as of this update (109 pre-existing + 9 added this pass). |

### Dependency map (as requested)

```
Market Data (Delta/Binance/Yahoo, cached)
    │
    ▼
Indicators (calculator.py, patterns.py, ema_mtf.py)
    │
    ▼
Signal Engine (engine.py) ──── force=True bypass ────┐
    │                                                  │
    ▼                                                  ▼
Live Signals (published, session-gated)      Backtest Runner (runner.py)
    │                                                  │
    ▼                                                  ▼
Notifications (Telegram/push/in-app)          Backtest Stats (_summarize)
    │                                                  │
    ▼                                                  ▼
Portfolio / Watchlist / Journal              Backtesting UI (dashboard/backtesting.html)
    │
    ▼
Analytics / Model Performance
```

The separate strategy-config backtest engine (`app/services/backtesting/engine.py`) sits parallel to this chain — it does not go through `signal_engine` at all, it re-implements strategy logic from stored config, which is why its trade schema diverges from the walk-forward runner's.

---

## 2. Phase 1 — P0 Backtesting Correctness: findings and fixes

### 2.1 FIXED — "Impossible win rate" (e.g. 4740%) display bug

**Root cause:** Purely a frontend double-multiplication, not a backend math error.

`app/services/backtest/runner.py::_summarize()` already computed `win_rate` and `raw_win_rate` correctly on a 0–100 scale (`round(len(wins) / decided * 100, 1)`), mathematically bounded to `[0, 100]` by construction. `frontend/templates/dashboard/backtesting.html` (the `isLive` branch of `showResults()`) multiplied this already-scaled value by 100 **again**: `(data.win_rate * 100 || 0).toFixed(1)`. A real 47.4% win rate rendered as `"4740.0%"` — this is the exact bug reported.

The same file also referenced `data.true_win_rate`, a field that **does not exist anywhere** in the walk-forward runner's response schema (it's a key from an unrelated endpoint, `/signals/backtest-analysis`, backed by `app/services/backtest/analyzer.py`). This was dead code that always evaluated to `(0||0)*100 = "0.0"`.

**Fix:** Removed the erroneous `* 100`; removed the dead `true_win_rate` reference; the "Raw (incl. expired)" sub-label now correctly reads the real `raw_win_rate` field instead of a non-existent one.

**Risk level:** Low (display-only change, no calculation logic touched). **Affected modules:** `frontend/templates/dashboard/backtesting.html` only. **Migration:** none.

### 2.2 FIXED — Live-engine trade data silently never displayed

**Root cause:** Key-name mismatch between the two backtest engines. The walk-forward runner returns its trade sample as `sample_trades`; the *other* engine (`app/services/backtesting/engine.py`) returns `trades_data`. Both the API route's trade-normalization loop (`app/api/v1/signals.py`, the `/signals/backtest` handler) and the frontend's equity-chart/trade-table code read `trades_data` unconditionally — which is always absent from the walk-forward engine's response. Result: for every "Live Engine" backtest, the equity/R curve chart and the trade list silently rendered empty, even though the backend had computed and returned real trade-level data (just under a different key).

**Fix:** API route and frontend both now branch on `isLive` to read `sample_trades` (walk-forward) vs `trades_data` (strategy-config engine) correctly.

**Risk level:** Low (read-path fix, no write/calculation changes). **Affected modules:** `app/api/v1/signals.py`, `frontend/templates/dashboard/backtesting.html`. **Migration:** none.

**Verified live** (production, disposable test account, deleted after verification): a real BTCUSDT/1h/90-day walk-forward backtest now displays `Win Rate (decided): 48.1%`, `Raw (incl. expired): 28.9%` — matching the raw API response exactly (13 wins / 27 decided = 48.1%, 13/45 = 28.9%) — with all 15 sample trades rendered in the table and a populated equity/R chart.

### 2.3 FIXED — Zero-trade backtests showed a misleading "0.0% Win Rate"

**Root cause:** When a walk-forward backtest ran successfully against sufficient historical data but the signal engine never fired a single signal in the window, `_summarize([])` correctly returns `win_rate: 0.0` — but the frontend rendered this identically to "traded and lost every time," with no indication that zero trades actually occurred.

**Fix:** `showResults()` now checks `totalTrades === 0` first and renders an explicit "No trades — the strategy generated no signals in this window" message instead of computing/showing any rate at all.

**Risk level:** Low. **Affected modules:** `frontend/templates/dashboard/backtesting.html`. **Migration:** none.

### 2.4 ADDED — Minimum sample-size warning

Below 20 decided trades, the Total Trades KPI now shows a "Small sample (&lt;20) — low confidence" sub-label. The threshold is a judgment call (documented inline in the code), not derived from a formal statistical test — flagged here for future refinement (e.g. a Wilson confidence interval) rather than a fixed magic number.

**Risk level:** Low (additive UI only). **Migration:** none.

### 2.5 ADDED — Regression tests for win-rate math

`tests/unit/test_backtest_win_rate.py` (9 tests) locks in the contract that `_summarize()`'s `win_rate`/`raw_win_rate` are always 0–100-scale, bounded, and sane across zero-trades / all-wins / all-losses / mixed win-loss-expired combinations (a sweep of ~500 combinations), plus that counts sum correctly and `profit_factor` never raises `ZeroDivisionError` with zero losing trades. There was previously **zero test coverage** of backtest win-rate math anywhere in the suite.

**Not yet covered by tests:** the strategy-config engine's (`app/services/backtesting/engine.py`) equivalent stats function — see §2.6.

### 2.6 FIXED — Partial-TP double-counting in the strategy-config engine

`app/services/backtesting/engine.py` (the *other* backtest engine, used by `POST /api/v1/backtesting/run`, not the walk-forward "Live Engine") appended a separate `trades` list entry for a T1 partial exit **in addition to** the eventual full-close entry for the same underlying signal. One live position became two rows in `_compute_stats`'s trade list, each classified win/loss *independently* — so a signal that banked a real gain at T1 and then gave a little back to a breakeven-minus-costs stop on the runner was reported as "1 win + 1 loss" instead of one net-profitable trade, inflating `total_trades` and skewing `win_rate`/`profit_factor`/`sharpe_ratio`/`sortino_ratio`/`avg_win`/`avg_loss` (all computed by iterating that same per-fill list) for any strategy using partial take-profits. This never produced an out-of-bounds value (win_rate stayed 0–100 by construction either way), which is why it's a distinct, subtler defect from §2.1 — but it directly skewed statistical accuracy, which Phase 1 explicitly calls out ("Correctly distinguish winning/losing/partially-successful trades").

**Fix:** every trade-list entry (partial exit, final close, and the end-of-data force-close) now carries an `entry_bar_index` linking it to the position it belongs to. A new `_consolidate_trades()` helper merges same-position legs into one logical trade (summed P&L/commission/slippage, `outcome` from the *net* P&L, `bars_held` = the full duration, `exit_reason` = what the position actually finished on) before `_compute_stats` computes any aggregate KPI. The raw per-fill rows are still returned verbatim in `trades_data` — this is a stats-aggregation fix only, no audit detail was removed.

**Verified live** on production with a disposable test account and a real BTCUSDT/1h backtest, then deleted: the run produced 14 raw trade-list rows (partial + final legs) that correctly consolidated to **8 real signals** (`total_trades: 8`, `winning_trades: 7`, `losing_trades: 1`, `win_rate: 87.5%`) — confirming partial-TP exits do occur on real data and the consolidation logic groups them correctly rather than just passing synthetic test cases.

**Risk level:** Medium (statistical-accuracy fix touching several aggregate KPIs at once — mitigated with 8 new unit tests before deploying, covering the single-leg pass-through case, partial-win+small-loss netting to one win, partial-win+bigger-loss netting to one loss, commission/slippage summation, independent positions staying separate, and a defensive case for rows with no linking key). **Affected modules:** `app/services/backtesting/engine.py`, `tests/unit/test_backtest_partial_exit_consolidation.py` (new, 8 tests). **Migration:** none (in-memory calculation only, no schema change) — existing `Backtest` rows already saved to the database retain their pre-fix numbers; only backtests run *after* this fix get the corrected consolidation.

### 2.6a FIXED (found while fixing §2.6) — Non-live backtest chart and trade table were also always empty

While fixing §2.6, found that `POST /api/v1/backtesting/run`'s response — which the Backtesting page's `showResults()` reads directly with no follow-up request — never included `equity_curve` or `trades_data`, even though `BacktestEngine._compute_stats()` computes both and the generic `setattr` loop in the `/run` handler already saves them to the `Backtest` row's columns. `Backtest.to_dict()` (used by this endpoint, by `list_backtests()`, and by `get_backtest()`) simply never serialized either field. `list_backtests()`'s existing, pre-existing pattern already worked around this correctly for the single-backtest detail view (`get_backtest()` manually bolts `equity_curve`/`trades_data` onto its response after calling `to_dict()`) — but `POST /run`'s handler didn't do the same, so the equity chart and full trade list were silently empty for **every** non-live/strategy-config backtest result, independent of and in addition to the §2.1/§2.2 live-engine bugs.

**Fix:** `POST /run`'s handler now bolts on `equity_curve`/`trades_data` the same way `get_backtest()` already does. Deliberately did **not** add these two fields to `to_dict()` itself, since `list_backtests()` (up to 50 history rows) shares that method and would otherwise carry a full ~500-point equity curve + ~100-trade array per row it never displays — added `winning_trades`/`losing_trades` (cheap scalars) directly to `to_dict()` since those are safe for every caller.

**Verified live**: the same test backtest above returned `equity_curve` (500 points) and `trades_data` (14 rows) in its `/run` response; the Backtesting page rendered the trade table with all 14 rows and a populated equity chart, both previously always empty.

**Risk level:** Low (additive — restores previously-computed-but-undelivered data; `list_backtests()` payload size unaffected). **Affected modules:** `app/models/backtest.py`, `app/api/v1/backtesting.py`. **Migration:** none.

### 2.7 NOT A BUG — Look-ahead bias / future-data leakage

Explicitly checked and found correctly guarded in both engines: `runner.py` computes signals from `df.iloc[:i+1]` and only simulates outcomes on `df.iloc[i+1:]`; `engine.py` uses an equivalent `df_r.iloc[max(0,i-warmup):i+1]` windowing with position management strictly on future bars. Duplicate/re-entrant signal execution is blocked via bar-skip logic (`i += max(step, max_bars)` in `runner.py`; `last_close_bar`/`position is None` checks in `engine.py`). No changes made or needed here.

### 2.8 MINOR — Walk-forward window averaging unweighted by trade count

`app/services/backtest/walk_forward.py` averaged `win_rate` across windows via unweighted `np.mean(win_rates)` rather than pooling trades first. A window with 3 trades and a window with 50 trades therefore counted equally toward the average. Not a >100% bug; a minor statistical-quality issue. **Risk level:** Low. Fixed below.

### 2.8 FIXED — Walk-forward aggregate win rate now reflects trade volume

**Root cause:** `run_walk_forward()` calculated `avg_win_rate` with `np.mean(win_rates)`, giving every time window equal weight even when their trade counts differed materially. A one-trade window therefore influenced the reported aggregate as much as a high-activity window with dozens of trades.

**Fix:** Each window now carries `winning_trades`, and the aggregate uses pooled `winning_trades / total_trades * 100`. The response also includes aggregate `total_trades` and `winning_trades` so the displayed percentage can be independently reconciled. A fallback derives the winner count from the legacy `total_trades`/`win_rate` fields when a mocked or older engine result lacks `winning_trades`.

**Risk level:** Low (aggregate reporting only; individual window calculations and trading behavior are unchanged). **Affected modules:** `app/services/backtesting/walk_forward.py`, `tests/unit/test_walk_forward.py`. **Migration:** none.

**Regression evidence:** Unit tests cover a 1-trade 0% window plus a 9-trade 100% window, proving the aggregate is 90% rather than the old 50%, and cover the legacy-result fallback. Production hot-copy verification completed on 2026-09-05: the app container's full suite reported `150 passed`, the live health endpoint returned `HTTP 200`, and the recent app/worker log scan contained no traceback/error matches. The containers were restarted before these checks; the change is API-only and the module is not imported by `app/tasks/`.

---

## 3. Phase 2 — AI Confidence & Model Accountability: findings and fixes

### 3.1 Architecture as verified (before any fix)

- **Real, trained ML models genuinely exist**: `app/services/ai/predictor.py` trains and persists RandomForest + XGBoost + LightGBM classifiers (each wrapped in `CalibratedClassifierCV(method="isotonic")`), pickled via `joblib` — confirmed 291 real `.pkl` files on disk in `data/models/`. A rule-based `_heuristic_fallback()` (probability in `[0.35, 0.65]`) covers the case where no ML library is importable. This is not aspirational code.
- **"LSTM" was false** — it appeared in UI copy and a build script's pitch-document generator ("Random Forest + XGBoost + LightGBM + LSTM") but no LSTM/tensorflow/keras code exists anywhere in the repository. Fixed — see §3.2.
- **The `confidence_score` shown on every regular, automatically-generated signal is 100% rule-based technical scoring — it is not, and never was, ML model output.** `SignalEngine._score_signal()` initializes `scores = {"trend": 0, "momentum": 0, "volume": 0, "pattern": 0, "ai": 10}` — `ai` is a hardcoded constant, never updated by any model, for every signal the scheduled/automatic pipeline generates (`app/tasks/signal_tasks.py`). The real ML ensemble is only invoked by a separate, manual, super-admin-only endpoint (`POST /signals/generate`), which adds a small "AI boost" scaled to a 0–20 range (`prediction.confidence * 0.2`) — at most ~2 points of the final `confidence_score`. This is a genuine, important gap between what "AI-powered" branding implies and what actually drives the number a regular user sees — **not fixed this pass** (a full redesign of `_compute_confidence`'s AI-weighting is a larger, separate decision — see §3.4 remaining items — this pass focused on removing active misrepresentation, not redesigning the underlying formula).
- **A confidence-calibration system already exists** and is more mature than expected: `app/api/v1/signals.py::_confidence_calibration_bands()` buckets closed signals into Weak/Moderate/Strong/Very Strong bands and compares actual vs. expected win rate, rendered as a chart on the main dashboard. Separately, `/model-performance` tracks the AI predictor's own directional accuracy (not bucketed by confidence). **Important nuance for future work**: the calibration chart evaluates the *rule-based* `confidence_score`, which per the point above isn't an ML probability to begin with — worth keeping in mind before extending it further.
- `/ai-insights` (the real ML-ensemble-backed page) shows a bare confidence percentage with zero accuracy-history or uncertainty context — not fixed this pass (flagged for §3.4).

### 3.2 FIXED — Fabricated per-model attribution in the "AI Decision Inspector"

**Root cause:** `frontend/static/js/pages/dashboard.js::loadInspector()` — the actual "AI Decision Inspector" the user's Phase 5 spec refers to (keeps entry/current/stop/targets/R:R/risk, a "Why AI Chose" checklist, warnings) — had a "Model Agreement" section presenting four supposedly-independent model scores:
```js
const models = [['XGBoost', s.ai_score], ['LightGBM', (s.trend_score + s.momentum_score) / 2],
['LSTM', (s.momentum_score + s.volume_score) / 2], ['Rule Engine', (s.trend_score + s.pattern_score) / 2]];
```
None of these came from the named models. `s.ai_score` is the hardcoded-10 placeholder from §3.1 (labeled "XGBoost"); "LightGBM" and "LSTM" were ad-hoc averages of the *same* trend/momentum/volume/pattern scores already shown in the checklist directly above, just relabeled with ML brand names; LSTM doesn't exist as a model at all. A user reading "XGBoost: 65%, LightGBM: 72%, LSTM: 58%" would reasonably believe three distinct real machine-learning models had independently analyzed the trade — none had. This is a direct violation of "Never represent model probability as guaranteed real-world probability unless statistically justified" and the broader no-fake-claims principle running through this whole engagement.

A second, related bug in the same function: the checklist's `['AI Model Agreement', (s.ai_score || 0) >= 55]` item could never pass for *any* signal in the system — `ai_score` is either the constant 10 (auto-generated signals) or, for the rare manually-generated signal with the real AI boost, capped at 20 (`prediction.confidence * 0.2`, verified by reading `/signals/generate`'s code) — both permanently below the 55 threshold sized for the *other* checks' 0–100 scale.

**Fix:** replaced the fabricated "Model Agreement" bars with an honestly-labeled "Confidence Factors" section showing the real components (Trend/Momentum/Volume/Pattern — the exact same data already backing the checklist above, just not double-counted under fake names). Removed the always-false "AI Model Agreement" checklist item rather than relabeling it to something equally uninformative, since it could not convey real information in either code path. Also removed "LSTM" from `/ai-insights`, `/ta-summary` (×2), and three lines in `scripts/build_pitch_document.py` (the pitch-document generator — a real, distributed document, so the same honesty standard applies there too).

**Verified live**: with a disposable test account (created, verified, deleted), called `loadInspector()` with a synthetic signal directly in the browser console — confirmed the checklist now shows exactly 4 real items (no "AI Model Agreement"), and "Confidence Factors" shows Trend/Momentum/Volume/Pattern with no ML-brand-name labels anywhere. Confirmed `/ai-insights`' subtitle now reads "Random Forest + XGBoost + LightGBM" with no LSTM claim.

**Risk level:** Low (frontend-only, no calculation logic changed — `confidence_score` itself, `trend_score`/`momentum_score`/etc. are untouched; only how they're *labeled and re-combined for display* changed). **Affected modules:** `frontend/static/js/pages/dashboard.js`, `frontend/templates/dashboard/ai_insights.html`, `frontend/templates/dashboard/ta_summary.html`, `scripts/build_pitch_document.py`. **Migration:** none. **Tests:** none added — this is a pure display/labeling fix with no new calculation logic to regression-test; existing 126 tests confirmed unaffected.

### 3.3 Remaining Phase 2 items (not started)

- Evidence/Counter-Evidence/Data-Quality/Uncertainty sections for `/ai-insights` and the AI Decision Inspector (the spec's core ask) — not yet designed or built.
- Historical-accuracy context alongside `/ai-insights`' bare confidence % (the existing `/model-performance` accuracy data could plausibly feed this without a new data pipeline — worth investigating first before building anything new).
- Whether/how to redesign `_compute_confidence`'s AI-weighting (currently a token +10 constant for 99%+ of signals) is a real product decision, not just a bug fix — flagged for discussion rather than acted on unilaterally.
- Model agreement (RF vs. XGBoost vs. LightGBM individually, not just the ensemble average) is not currently exposed anywhere — would require exposing `_ensemble_predict`'s per-model `predict_proba` outputs, not just the averaged result.
- Market-regime confidence and data-freshness indicators near signals/AI insights — genuinely absent everywhere (confirmed via search), overlaps with Phase 3 (Data Quality) and Phase 4 (Signal lifecycle) — better tackled there.

---

## 4. Phase 3 — Data Quality Engine: findings and fixes

### 4.1 Investigation summary

Before writing anything, the fetch-to-signal path was traced end-to-end (`app/services/data/fetcher.py`, `app/services/signals/engine.py`, `app/models/api_config.py`, the Admin API Configs page). Findings:

- **Already solid, deliberately not touched:** per-provider circuit breakers (`_CircuitBreaker`, Redis-backed, cross-process, consecutive-failure threshold + recovery timeout), retry-with-backoff, the admin market-pause gate (`blocked_data_markets()` / `APIConfig.status`), and the live trading-session gate (`_session_gate` / `_SESSIONS`). These handle *availability* (can we reach the provider) correctly.
- **The real gap:** none of the above check the *content* of a technically-successful fetch. A provider can return 200 OK with stale, gapped, duplicated, or OHLC-inconsistent candles, and it sails through `fetch()` → cache → `generate_signal()` with only a bare `len(df) >= 60` row-count check — no timestamp-age check, no OHLC sanity check, no duplicate/gap detection anywhere in the entire path.
- **A timezone landmine:** Delta/Binance return tz-naive UTC timestamps; Yahoo Finance returns tz-aware timestamps localized per-instrument (confirmed live on production: NSE → `Asia/Kolkata`, US equities → `America/New_York`, forex → `Europe/London`). No normalization existed anywhere. A naive "now − last candle time" staleness check would either raise `TypeError` (naive vs. aware) or silently misjudge the gap by the zone offset depending on which provider's data it happened to receive.
- **Admin API Configs' health fields are cosmetic, not live:** they're updated only by a manual "Test Connection" click, not by the real background fetcher — flagged for Phase 6/9 (Admin UX/RBAC), not fixed here (out of scope for the data-quality check itself; wiring it in is a separate, larger change to the admin page).
- **Operational finding, not a defect in this codebase:** live-checking this on production revealed Yahoo Finance is currently **admin-paused** for all four markets that depend on it — `commodity`, `forex`, `index`, and `indian_stock` (`APIConfig.status = "paused"`, `error_count: 0`, i.e. manually paused, not a circuit-breaker trip). Only `crypto` (Delta Exchange) is currently live. This means signal generation is currently producing zero output for indian_stock/commodity/index/forex platform-wide, independent of anything in this Phase 3 change. Worth the user's attention as a separate follow-up; not touched here since toggling live provider state wasn't requested and is a business/operational decision, not a Phase 3 correctness fix.

### 4.2 Fix: `app/services/data/quality.py` (new) — data quality gate

New pure, dependency-free module (no DB/network/Flask — reusable from the signal engine, both backtest engines, TA Summary, AI Insights, and eventually the Admin API Configs page) exposing `assess_data_quality(df, market, timeframe) -> dict`:

- `_normalize_utc()` converts both tz-naive (assumed UTC) and tz-aware (any zone) timestamps to a common UTC `datetime` before any age comparison — the fix for the timezone landmine above.
- Checks: timestamp freshness (GREEN/YELLOW/RED by bar-width multiples), duplicate timestamps, gaps larger than 2 bar-widths, invalid OHLC relationships (`high < low`, non-positive prices, etc.), negative/anomalous volume.
- Returns `{"status": "GREEN"|"YELLOW"|"RED", "issues": [...], "last_candle_age_seconds": float|None, "hard_invalid": bool}`. `hard_invalid` distinguishes genuine data corruption (bad OHLC, duplicate candles, missing columns/rows — wrong regardless of context) from staleness/gaps/volume-spikes, which are only meaningful for *live* signal generation — a backtest deliberately replays historical candles, and comparing their timestamp to wall-clock "now" would flag every single one as stale.

### 4.3 Fix: `app/services/signals/engine.py` — wired as a new gate

Added immediately before Stage 1 (the existing session gate), inside `generate_signal()`'s `try` block:

```python
quality = assess_data_quality(df, market, timeframe)
if quality["hard_invalid"] or (not force and quality["status"] == "RED"):
    logger.warning("Data quality gate blocked signal for %s %s: %s", ...)
    return None
```

This mirrors the codebase's own existing precedent for every other live-only gate in this function (`if not force and not self._session_gate(market): return None`) so staleness-based blocking is correctly bypassed during backtesting (`force=True`) exactly the way the session gate already is, while hard data-integrity problems block unconditionally in both live and backtest paths, since corrupt data is never valid to trade or backtest on.

### 4.4 Tests: `tests/unit/test_data_quality.py` (new, 22 tests)

Covers: `_normalize_utc()` on naive/aware/equivalent-instant inputs; GREEN on fresh data for all four timezone shapes actually seen in production (naive/crypto, `Asia/Kolkata`, `Europe/London`, `America/New_York`); RED on stale data for both naive and aware inputs (the specific case that would previously raise `TypeError` or misjudge the age — now proven not to); YELLOW at the borderline threshold; every `hard_invalid` case (empty/`None` df, missing column, duplicate timestamps, invalid OHLC, negative price, negative volume) confirmed to set `hard_invalid=True`; soft anomalies (gap, volume spike) confirmed `hard_invalid=False`; never-raises on a single-row df and an unknown timeframe.

### 4.5 Live verification

- Full suite: **148 passed** (up from 126 pre-Phase-3; the delta is the 22 new tests), run inside the `app` container on production after `docker compose restart app worker`.
- Crypto (tz-naive), real production data: `XAUTUSDT` → `{'status': 'GREEN', 'issues': [], 'last_candle_age_seconds': 534.0, 'hard_invalid': False}` — confirms the naive-timestamp path works correctly against real live data.
- Yahoo-sourced (tz-aware) assets could not be exercised against *live* production data in this pass because Yahoo is currently admin-paused for all four markets that use it (§4.1 finding above) — even a direct `YahooFetcher.fetch_ohlcv()` call (bypassing the admin pause) returned no data, suggesting Yahoo itself is currently unreachable/rate-limited from this server, which is plausibly *why* it was paused. The tz-aware path is instead verified via the unit tests in §4.4, which test the exact same `_normalize_utc()` function against real timezone data matching what Yahoo returns for each market (`Asia/Kolkata`, `Europe/London`, `America/New_York`).
- No tracebacks in `app`/`worker` logs since restart despite continued real signal-generation/feature-engineering activity, confirming the new gate doesn't error on the live code path.

### 4.6 Remaining Phase 3 items (not done in this pass)

- Wiring real `assess_data_quality()` output into the Admin API Configs page's health display (currently only updated by manual "Test Connection" clicks) — a larger, separate change to that admin page, overlaps Phase 6/9.
- Persisting a `data_quality` status per generated `Signal` (would need a new DB column/migration — deliberately not added speculatively; the current fix enforces correctness via the gate itself without requiring a schema change) — worth doing once Phase 6 (Dashboard UX) needs to *display* freshness per signal.
- The Yahoo-paused-for-all-4-non-crypto-markets operational finding above needs the user's decision, not a code fix.

---

## 5. Phase 4 — Signal Engine Hardening: findings and fixes

### 5.1 Investigation summary

Traced the real signal-lifecycle path end-to-end before looking for anything to fix: `app/tasks/signal_tasks.py` (auto-generation scheduler), `app/tasks/data_tasks.py` (`_check_outcome`, `_claim_signal_close`, `close_and_record_signals`, `check_signals_for_price`). This turned out to be **already well-hardened** — worth recording as a verified-good finding, not just a list of defects:

- Every close-out path (the 5-min scheduled sweep, the ~15s real-time ticker/WebSocket-driven check, and the 30-min prediction evaluator) uses `_claim_signal_close()` — a single conditional `UPDATE ... WHERE status='active'` — so two overlapping jobs racing to close the same signal can't both write a duplicate `SignalHistory` row. This is a real, deliberate race-condition fix (evidenced by the function's own docstring describing the exact bug it replaced), not something written for this pass.
- Signal generation itself (`generate_signals_for_timeframe`) writes one signal at a time (not one shared transaction) specifically so one duplicate `IntegrityError` (caught via a genuine partial unique index, `uq_signals_active_asset_tf`) can't roll back every other legitimately-new signal generated in the same batch — also pre-existing, already correct.
- No defect found in the core status-transition logic (`active` → `hit_target`/`hit_sl`/`expired`) itself.

### 5.2 FOUND & FIXED — `LiveReadLog`'s documented "same condition as a real signal" claim was false

**Root cause:** `app/api/v1/signals.py::_frozen_live_read()` freezes a Terminal "live read" preview card (shown when no real persisted `Signal` exists yet for an asset+timeframe) and only resolves/logs its hypothetical outcome once price reaches the frozen stop-loss **or `target3`** (`cached.get("target3")`, the final/hardest of the three take-profit levels). Its own docstring, and `_close_live_read_log()`'s docstring, both explicitly claimed this is "the same condition that would close a real persisted signal." It is not: a real `Signal` closes as a win the moment price reaches **`target1`** (`app/tasks/data_tasks.py::_check_outcome`) — the first, easiest target, not the third and hardest.

This surfaces as a real, user-facing accuracy claim: `GET /signals/live-read-performance` (any logged-in user, not admin-only) computes `win_rate = wins / resolved * 100` from these logs and is displayed as a plain "Win Rate" stat on `/performance` (`dashboard/performance.html`'s "Terminal Live Reads" card), directly next to the real-signal performance numbers on the same page — with nothing telling the user the two percentages are computed on different, non-comparable bars. Compounding this: a read that reaches `target1`/`target2` and then reverses without ever reaching stop-loss or `target3` never resolves at all — it just sits at `outcome=None` until its cache entry (TTL-matched to the signal-validity window) ages out and gets silently replaced, meaning it's excluded from `win_rate`'s denominator entirely rather than counted as an "expired/neutral" outcome the way a real `Signal` correctly is. Net effect: the displayed "Win Rate" for Terminal live reads is measured on a materially different, harder-to-win, and statistics-biased-by-silent-exclusion basis than the real-signal win rate shown right next to it — exactly the kind of unqualified-and-non-comparable accuracy number this engagement is about catching.

**Fix (this pass, intentionally scoped down from the full redesign — see §5.3):** Deliberately did **not** change the resolution trigger itself (`target3`) — a look at `tests/integration/test_terminal_live_read_freeze.py::test_price_reaching_final_target_recomputes_a_fresh_read` shows this is a separate, legitimately-intentional, already-tested UX decision (don't reshuffle a card's displayed entry/stop/targets into a brand-new setup just because price partially played out — keep showing the same plan until the whole hypothetical trade has run its course). Changing that would have been scope creep into a different, working feature. Instead, fixed the actual defect — the false "same as a real signal" claim and the lack of any caveat where the number is shown:
- Corrected both docstrings (`_frozen_live_read`, `_close_live_read_log`) to accurately state the resolution condition is `target3`, explicitly flagged as a stricter, non-comparable bar versus a real Signal's `target1`-based close.
- Added an explicit warning docstring on `live_read_performance()` itself spelling out the non-comparability and the silent-exclusion-from-denominator issue, so nobody building on this endpoint later repeats the original false assumption.
- Added a user-facing caption on `/performance`'s "Terminal Live Reads" card: *"Win Rate here uses a stricter bar (must reach the final target) than real signals (which count a win at the first target), so the two percentages are not directly comparable. 'Still Open' includes reads that may never resolve and age out uncounted."*

**Risk level:** Low (documentation/comments + one additive UI caption only — zero calculation or resolution logic changed, so the existing, deliberately-tested freeze/refresh behavior is untouched). **Affected modules:** `app/api/v1/signals.py`, `frontend/templates/dashboard/performance.html`. **Migration:** none. **Tests:** none added (no logic changed to regression-test); existing 148 tests, including all 4 in `test_terminal_live_read_freeze.py`, confirmed passing unchanged both locally and on the server.

**Verified live**: disposable test account created (temporarily elevated to view the Basic+-gated `/performance` page), confirmed via direct DOM query that the new caption text renders exactly as written on the production page's "Terminal Live Reads" card; account and all FK-dependent rows deleted afterward.

### 5.3 Remaining Phase 4 items (not done in this pass — larger, separate changes)

- **A real fix for the underlying design gap**, not just the disclosure added above: give `LiveReadLog` its own `expires_at` (mirroring `Signal.expires_at`) and a scheduled sweep that marks timed-out-without-resolving rows `outcome="expired"` (neutral), the way real signals already correctly do — this needs a new DB column + migration + a background job, which is why it wasn't done speculatively in this pass. Once that exists, a second, real product decision follows: should `live_read_performance()`'s win condition be changed to `target1` to make it genuinely comparable to real-signal win rate (as its docstrings originally, incorrectly, claimed it already was), or is measuring against the harder `target3` bar an intentional, different metric that just needs to stay clearly labeled as such? That's a product call, not a bug fix — flagged for discussion.
- Signal-lifecycle reproducibility metadata (engine version / model version stamped on each generated `Signal`) — overlaps the Phase 1 item already flagged in §2.8/§5-remainder; still not started.
- The rest of Phase 4 as specified (signal versioning at the schema level) beyond the one concrete defect found and fixed above.

---

## 6. Phase 5 — AI Decision Inspector: findings and fixes

### 6.1 FOUND & FIXED — Evidence/Counter-Evidence data existed but was never shown

**Root cause:** `SignalEngine.generate_signal()`/`analyze()` already compute and persist a structured, per-factor breakdown of what supported vs. opposed the final call — `reasoning_detail`, a list of `{text, lean, aligned}` (see `SignalEngine._labeled_reasons()`), where `aligned` marks whether that factor's lean agreed with the signal's final direction or was outweighed by something stronger (e.g. a reversal pattern beating a still-bullish EMA trend). This is real, already-computed, already-persisted data (`Signal.reasoning_detail`, a JSON column, included in `Signal.to_dict()` and therefore in every `/signals` API response) — and the server-side `_build_retrospective_note()` used by `/signal-journal` already reads it. But the AI Decision Inspector (`frontend/static/js/pages/dashboard.js::loadInspector()`) never used it at all: it only showed a fixed 4-item checklist (score-vs-threshold pass/fail, no actual reasons) and a "Confidence Factors" bar chart. Counter-evidence in particular — a factor that pointed the other way but lost — was silently dropped everywhere in the UI even though it was sitting in the API response the whole time. This is exactly the "Evidence/Counter-Evidence" gap flagged as not-yet-built in §3.3 and §4.1 of this audit.

**Fix:** `loadInspector()` now splits `s.reasoning_detail` on its existing `aligned` flag into two new sections — "Evidence Supporting {BUY/SELL}" (aligned factors, green check icons, reusing the existing `.insp-check`/`.insp-checks` styling) and "Counter-Evidence (outweighed)" (non-aligned factors, only rendered when at least one exists — most signals have none). No new backend work was needed; this is a pure frontend addition surfacing data the engine was already producing.

**Risk level:** Low (additive UI only, reuses existing CSS classes, no calculation/API changes). **Affected modules:** `frontend/static/js/pages/dashboard.js`. **Migration:** none. **Tests:** none added — no test infrastructure exists for this vanilla-JS dashboard file (confirmed: no frontend build/test pipeline in this repo), consistent with how the Phase 2 §3.2 frontend-only fix was handled; existing 148 backend tests confirmed passing unchanged.

**Verified live** (production, disposable test account, deleted after): fetched a real live `AVAXUSDT` BUY signal via the actual `/api/v1/signals/` endpoint and called `loadInspector()` with it directly in the browser — confirmed "Evidence Supporting BUY" rendered all 8 real, live reasoning factors ("EMA9>EMA21 (uptrend)", "Golden cross zone", "Price above VWAP", "SuperTrend bullish", "Price above Ichimoku cloud", "RSI bullish zone (60)", "MACD bullish crossover", "Volume in line with average") with correct green-check styling; confirmed the Counter-Evidence section correctly does not render when a signal has none (this one had none); confirmed the rest of the Inspector (entry/stop/targets, checklist, warnings, Confidence Factors) still renders correctly alongside the new sections.

### 6.2 Remaining Phase 5 items (not done in this pass)

- Historical-accuracy context alongside the Inspector's confidence % (still flagged from §3.3 — the existing `/model-performance` and confidence-calibration-band data could plausibly feed this).
- Data-quality status (now available from Phase 3's `assess_data_quality()`) is not yet surfaced in the Inspector — a natural next addition now that both pieces exist independently.
- Market-regime confidence context (`s.regime` already exists on every signal but isn't shown in the Inspector itself, only used elsewhere) — not added this pass, scoped separately to keep this change to one concrete addition.
- **A much deeper AI/ML rigor spec was handed over on 2026-09-05, to start once the current phase of this 16-phase pass reaches a natural stopping point** — see the user-provided spec (calibration separation, ensemble redesign, drift monitoring, leakage testing, shadow models, per-model independent evaluation, a new `/admin/ai-quality` page, etc.). That spec substantially deepens and overlaps this section's remaining items and Phase 2/3's remaining items — treat it as the rigorous continuation of this work, not a separate backlog, when it's time to start it.

---

## 7. Remaining P0/P1 items from the full 16-phase spec (not started)

This audit and the fixes above cover Phase 0 (discovery), the highest-priority item of Phase 1 (win-rate correctness + its immediately adjacent display bugs, including the partial-TP consolidation fix), one concrete, well-scoped Phase 2 item (fabricated per-model attribution), the core Phase 3 item (the data quality gate), one concrete Phase 4 item (the LiveReadLog non-comparable-accuracy-claim fix), and one concrete Phase 5 item (Evidence/Counter-Evidence in the AI Decision Inspector). The full spec's remaining phases are substantial, multi-week-scale work and have **not** been started:

- Phase 1 (remainder): commission/slippage/spread modeling audit, Sharpe/Sortino/recovery-factor calculation audit, reproducibility metadata (backtest ID, engine version, model version) on every result, walk-forward's unweighted window averaging (§2.8).
- Phase 2 (remainder): see §3.3 above.
- Phase 3 (remainder): see §4.6 above.
- Phase 4 (remainder): see §5.3 above.
- Phase 5 (remainder): see §6.2 above.
- Phases 6–16: as specified, untouched.

Each should get its own investigation-then-fix pass with the same evidence-based discipline used here (read the actual code, verify claims against real behavior, add regression tests, verify live before calling it done) rather than being implemented speculatively in one large batch.

---

## 8. Files changed this pass

**Session 1 (win-rate display bugs, §2.1–2.5):**
- `frontend/templates/dashboard/backtesting.html` — win-rate double-multiplication fix, `sample_trades`/`trades_data` key fix, zero-trade empty state, min-sample-size warning.
- `app/api/v1/signals.py` — `sample_trades`/`trades_data` key fix in the `/signals/backtest` trade-normalization loop.
- `tests/unit/test_backtest_win_rate.py` — new, 9 tests.

**Session 2 (partial-TP consolidation, §2.6–2.6a):**
- `app/services/backtesting/engine.py` — `entry_bar_index`/`leg_units` linking fields on every trade-list append site, new `_consolidate_trades()` helper, `_compute_stats()` now computes aggregate KPIs from consolidated (per-signal) trades while `trades_data` stays raw (per-fill).
- `app/models/backtest.py` — `winning_trades`/`losing_trades` added to `to_dict()`.
- `app/api/v1/backtesting.py` — `POST /run` now includes `equity_curve`/`trades_data` in its response, matching `get_backtest()`'s existing pattern.
- `tests/unit/test_backtest_partial_exit_consolidation.py` — new, 8 tests.

**Session 3 (Phase 2 — fabricated per-model attribution, §3.2):**
- `frontend/static/js/pages/dashboard.js` — removed fabricated "Model Agreement" per-model scores from the AI Decision Inspector, replaced with honestly-labeled "Confidence Factors"; removed the always-false "AI Model Agreement" checklist item.
- `frontend/templates/dashboard/ai_insights.html`, `frontend/templates/dashboard/ta_summary.html` — removed false "LSTM" claim from ensemble-description copy (3 occurrences).
- `scripts/build_pitch_document.py` — removed false "LSTM" claim from the pitch-document generator (3 occurrences).

**Session 4 (Phase 3 — Data Quality Engine, §4):**
- `app/services/data/quality.py` — new module: `assess_data_quality()` + `_normalize_utc()`.
- `app/services/signals/engine.py` — new data-quality gate wired in immediately before the Stage 1 session gate, using the existing `if not force` precedent pattern.
- `tests/unit/test_data_quality.py` — new, 22 tests.

**Session 5 (Phase 4 — LiveReadLog non-comparable win-rate claim, §5.2):**
- `app/api/v1/signals.py` — corrected `_frozen_live_read()`/`_close_live_read_log()`/`live_read_performance()` docstrings to accurately describe the `target3`-based resolution and its non-comparability to real-signal `target1`-based outcomes; no logic changed.
- `frontend/templates/dashboard/performance.html` — added a user-facing caption on the "Terminal Live Reads" card clarifying the Win Rate shown there isn't directly comparable to real-signal win rate.

**Session 6 (Phase 5 — Evidence/Counter-Evidence in the AI Decision Inspector, §6.1):**
- `frontend/static/js/pages/dashboard.js` — `loadInspector()` now renders "Evidence Supporting {direction}" and "Counter-Evidence (outweighed)" sections from the already-computed `reasoning_detail` field.

- `docs/IMPROVEMENT_AUDIT.md` — this file.

**Database changes:** none across all six sessions; `Backtest` rows already had the `winning_trades`/`losing_trades`/`equity_curve`/`trades_data` columns, they just weren't being serialized. **API contract changes:** none breaking — `POST /backtesting/run`'s response gained fields (`equity_curve`, `trades_data`, `winning_trades`, `losing_trades`) it was always supposed to return per its own `to_dict()`/`get_backtest()` sibling pattern; no field removed or renamed. Phase 3 adds a new internal gate to `generate_signal()` that can return `None` (no signal) in cases that previously would have produced one — specifically only when data is stale (live path only) or corrupt (both live and backtest) — no existing route, response shape, or subscription rule changed. **No destructive migration. No new credentials or secrets introduced.**
