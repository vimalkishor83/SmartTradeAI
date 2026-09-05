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

### 2.9 FIXED — Registration input was not normalized or validated before persistence

**Root cause:** The public registration route checked only whether the three keys existed. It accepted whitespace-padded usernames, stored email addresses with inconsistent casing, accepted malformed email strings, and allowed passwords shorter than the application's stated minimum. This created avoidable duplicate-account behavior and weak-input risk at the public boundary.

**Fix:** Registration now trims usernames, lowercases emails, validates username length/characters, enforces an 8-256 character password range, and rejects obviously malformed email values before uniqueness checks or database writes. Existing terms acceptance, broker validation, referral handling and pending-approval behavior are unchanged.

**Risk level:** Low (rejects invalid input and normalizes new records only). **Affected modules:** `app/auth/routes.py`, `tests/unit/test_registration_validation.py`. **Migration:** none.

**Regression evidence:** Four unit tests cover normalization, invalid usernames, short passwords, malformed emails, missing fields and the no-write behavior for invalid input. Production deployment verification completed on 2026-09-05: the app container's full suite reported `154 passed`, the live health endpoint returned `HTTP 200`, the root page returned `HTTP 200`, and the recent app/worker log scan contained no traceback/error matches. The registration tests use isolated client IPs so Redis-backed rate limiting cannot mask validation responses.

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
- Returns the original status/issue fields plus a stable metadata contract: `provider`, `market`, `timeframe`, `candle_count`, `expected_interval_seconds`, `last_candle_at` (UTC ISO-8601), and `warnings`. `hard_invalid` distinguishes genuine data corruption (bad OHLC, duplicate candles, missing columns/rows — wrong regardless of context) from staleness/gaps/volume-spikes, which are only meaningful for *live* signal generation — a backtest deliberately replays historical candles, and comparing their timestamp to wall-clock "now" would flag every single one as stale. The optional `provider` argument is backward-compatible for existing callers that only know the market.

### 4.3 Fix: `app/services/signals/engine.py` — wired as a new gate

Added immediately before Stage 1 (the existing session gate), inside `generate_signal()`'s `try` block:

```python
quality = assess_data_quality(df, market, timeframe)
if quality["hard_invalid"] or (not force and quality["status"] == "RED"):
    logger.warning("Data quality gate blocked signal for %s %s: %s", ...)
    return None
```

This mirrors the codebase's own existing precedent for every other live-only gate in this function (`if not force and not self._session_gate(market): return None`) so staleness-based blocking is correctly bypassed during backtesting (`force=True`) exactly the way the session gate already is, while hard data-integrity problems block unconditionally in both live and backtest paths, since corrupt data is never valid to trade or backtest on.

### 4.4 Tests: `tests/unit/test_data_quality.py` (24 tests)

Covers: `_normalize_utc()` on naive/aware/equivalent-instant inputs; GREEN on fresh data for all four timezone shapes actually seen in production (naive/crypto, `Asia/Kolkata`, `Europe/London`, `America/New_York`); RED on stale data for both naive and aware inputs (the specific case that would previously raise `TypeError` or misjudge the age — now proven not to); stable metadata for known and unknown providers plus empty responses; YELLOW at the borderline threshold; every `hard_invalid` case (empty/`None` df, missing column, duplicate timestamps, invalid OHLC, negative price, negative volume) confirmed to set `hard_invalid=True`; soft anomalies (gap, volume spike) confirmed `hard_invalid=False`; never-raises on a single-row df and an unknown timeframe.

### 4.5 Live verification

- Local unit baseline: **119 passed** (24 data-quality tests, including the new metadata contract).
- Production verification completed on 2026-09-05 after rebuilding app/worker: the full suite reported **156 passed**, `/api/v1/system/health` returned `HTTP 200`, the root page returned `HTTP 200`, all containers were healthy/running, and the fresh app/worker log scan contained no traceback/error matches. The additive contract is now available to future API and admin/UI consumers; existing signal-engine behavior is unchanged.
- Crypto (tz-naive), real production data: `XAUTUSDT` → `{'status': 'GREEN', 'issues': [], 'last_candle_age_seconds': 534.0, 'hard_invalid': False}` — confirms the naive-timestamp path works correctly against real live data.
- Yahoo-sourced (tz-aware) assets could not be exercised against *live* production data in this pass because Yahoo is currently admin-paused for all four markets that use it (§4.1 finding above) — even a direct `YahooFetcher.fetch_ohlcv()` call (bypassing the admin pause) returned no data, suggesting Yahoo itself is currently unreachable/rate-limited from this server, which is plausibly *why* it was paused. The tz-aware path is instead verified via the unit tests in §4.4, which test the exact same `_normalize_utc()` function against real timezone data matching what Yahoo returns for each market (`Asia/Kolkata`, `Europe/London`, `America/New_York`).
- No tracebacks in `app`/`worker` logs since restart despite continued real signal-generation/feature-engineering activity, confirming the new gate doesn't error on the live code path.

### 4.6 Remaining Phase 3 items (not done in this pass)

- Wiring real `assess_data_quality()` output into the Admin API Configs page's health display (currently only updated by manual "Test Connection" clicks) — a larger, separate change to that admin page, overlaps Phase 6/9.
- Persisting a `data_quality` status per generated `Signal` (would need a new DB column/migration — deliberately not added speculatively; the current fix enforces correctness via the gate itself without requiring a schema change) — worth doing once Phase 6 (Dashboard UX) needs to *display* freshness per signal.
- The Yahoo-paused-for-all-4-non-crypto-markets operational finding above needs the user's decision, not a code fix.

### 4.7 IMPLEMENTED — Persist data-quality context on generated signals

The data-quality gate previously made the correct allow/block decision but discarded its result before persistence. Signals now snapshot the additive `data_quality` contract, including status, provider when known, candle count, expected interval, normalized last-candle timestamp, age and warnings. The field is nullable for historical rows, is serialized by `Signal.to_dict()`, and is included by automatic generation, manual generation and signal-journal responses. This gives the dashboard and terminal a trustworthy basis for freshness/integrity UI instead of reconstructing quality after the fact.

**Risk level:** Medium (nullable JSON migration plus additive API field; existing rows and response fields remain compatible). **Affected modules:** `app/models/signal.py`, `app/services/signals/engine.py`, `app/api/v1/signals.py`, `migrations/versions/3b7c9d1e2f4a_add_data_quality_to_signals.py`, `tests/unit/test_signal_quality_contract.py`. **Migration:** add nullable `signals.data_quality`.

**Regression evidence:** Full local unit baseline passed with **120 tests**. Production verification completed on 2026-09-05 after the migration-backed app/worker rebuild: the full suite reported **157 passed**, both app and worker were running with app healthy, the health and root endpoints returned `HTTP 200`, and the fresh app/worker log scan contained no traceback/error matches.

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

### 5.3 Remaining Phase 4 items (partially completed; larger, separate changes remain)

- **Completed in §7.22:** `LiveReadLog` now has its own `expires_at`, a migration/backfill, and a scheduled sweep that marks timed-out-without-resolving rows `outcome="expired"` (neutral). The remaining product decision is whether `live_read_performance()` should change its win condition to `target1` to become comparable to real-signal win rate, or keep the harder `target3` bar as a separately labeled metric. The implementation keeps target3 because changing the definition of an existing metric requires an explicit product decision.
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

### 6.3 IMPLEMENTED — Surface data quality and market regime in the Decision Inspector

The dashboard Decision Inspector now displays the persisted signal data-quality status, candle age, provider, candle count and market regime beside the trade plan. Unknown or historical values degrade to explicit labels rather than fabricated certainty, and the regime copy states that it describes the observed environment rather than predicting profit. This gives users the context needed to decide whether a signal is actionable without changing signal selection or confidence math.

**Risk level:** Low (additive UI-only rendering with safe provider escaping). **Affected modules:** `frontend/static/js/pages/dashboard.js`, `frontend/static/css/main.css`. **Migration:** none.

**Regression evidence:** JavaScript syntax validation and whitespace checks passed locally. Production app service was rebuilt and restarted from commit `c4dcbcb`; authenticated visual browser verification remains a follow-up because no browser control surface was available in this session.

### 7.4 IMPLEMENTED — Coalesce duplicate dashboard GET requests

The primary dashboard API client now coalesces identical concurrent `GET` requests by URL and token. This targets the observed pattern where multiple dashboard modules initialize together and request the same summary/performance/market data independently. The map is in-flight only: it is removed when the request settles, so this reduces duplicate network/database work without introducing stale client-side caching or changing response semantics.

**Risk level:** Low (GET-only request coalescing, token included in the key). **Affected modules:** `frontend/static/js/app.js`. **Migration:** none.

**Regression evidence:** JavaScript syntax validation and whitespace checks passed locally. Production deployment completed on 2026-09-05 from commit `8c0cbb1`: the app container is healthy, the worker and dependencies are healthy, the full suite reported **159 passed** in 42.86s, health and root endpoints returned `HTTP 200`, and the fresh app/worker log scan contained no traceback/error matches. Authenticated visual browser verification remains a follow-up because no browser control surface was available in this session.

### 7.1 IMPLEMENTED — Bound signal-list pagination for API performance

The authenticated signal-list endpoint previously converted user-controlled `page` and `per_page` values directly with `int()`. Invalid input could produce a 500 response, while an extremely large page size could trigger an oversized database query and JSON response. A shared pagination helper now normalizes invalid/negative pages and clamps signal-list responses to a maximum of 100 records, protecting database and network budgets without changing normal requests.

**Risk level:** Low (input normalization and an upper bound; default behavior is unchanged). **Affected modules:** `app/services/pagination.py`, `app/api/v1/signals.py`, `tests/unit/test_pagination.py`. **Migration:** none.

**Regression evidence:** Targeted pagination tests and the full local unit baseline passed with **122 tests**. Production verification completed on 2026-09-05 after rebuilding the app service from `a8b4c47`: the full suite reported **159 passed**, health and root endpoints returned `HTTP 200`, the app remained healthy, and the fresh app/worker log scan contained no traceback/error matches.

### 7.2 IMPLEMENTED — Apply pagination limits to signal history

The signal-history endpoint duplicated the old unbounded `int()` parsing used by the signal list. It now uses the same shared positive-page and maximum-100-record contract, so the Performance and Signal Journal data paths have the same failure behavior and response budget. This is an additive performance hardening change with no default pagination change.

**Risk level:** Low (shared input normalization; default page size remains 20). **Affected modules:** `app/api/v1/signals.py`, `app/services/pagination.py`, `tests/unit/test_pagination.py`. **Migration:** none.

**Regression evidence:** The shared pagination tests and full local unit baseline passed with **122 tests**. Production verification completed on 2026-09-05 after rebuilding the app service from `3aa65c6`: the full suite reported **159 passed**, health and root endpoints returned `HTTP 200`, the app remained healthy, and the fresh app/worker log scan contained no traceback/error matches.

### 7.3 IMPLEMENTED — Standardize admin collection pagination

Admin user, session, audit-log and system-log endpoints now reuse the shared pagination guard. Invalid page values no longer raise conversion errors, and audit-log page sizes retain their existing default of 50 while remaining capped at 200. This removes another set of duplicate pagination rules and protects administrative screens from accidental oversized responses.

**Risk level:** Low (input normalization; default response sizes are unchanged). **Affected modules:** `app/api/v1/admin.py`, `app/services/pagination.py`, `tests/unit/test_pagination.py`. **Migration:** none.

**Regression evidence:** Targeted pagination tests and the full local unit baseline passed before this change. Production verification completed on 2026-09-05 after rebuilding the app service from `85ebd8c`: the full suite reported **159 passed**, health and root endpoints returned `HTTP 200`, the app remained healthy, and the fresh app/worker log scan contained no traceback/error matches.

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

### 7.5 IMPLEMENTED — Bound remaining collection pagination

The news, journal, and notifications collection routes now use the shared pagination guards. Invalid page values normalize to page 1, invalid page sizes use the documented defaults, and requested page sizes are capped at 100 records. This closes the same input-safety and response-budget gap previously found in signal history and admin collections.

**Risk level:** Low (normal defaults and valid requests are unchanged). **Affected modules:** `app/api/v1/news.py`, `app/api/v1/journal.py`, `app/api/v1/notifications.py`. **Migration:** none.

**Regression evidence:** Local syntax validation, whitespace validation, and the unit pagination regression suite passed. Production deployment completed on 2026-09-05 from commit `391f382`: the app container is healthy, the worker and dependencies are healthy, the full suite reported **159 passed** in 43.52s, health and root endpoints returned `HTTP 200`, and the fresh app/worker log scan contained no traceback/error matches.

### 7.6 IMPLEMENTED — Harden unified signal journal pagination

The unified `/signals/journal` endpoint already capped page size at 100, but malformed numeric query parameters still raised `ValueError` and could return a 500. It now uses the shared pagination guards, preserving the existing defaults and cap while normalizing invalid input safely.

**Risk level:** Low (valid pagination behavior is unchanged). **Affected modules:** `app/api/v1/signals.py`. **Migration:** none.

**Regression evidence:** Local syntax validation and whitespace validation passed. Production deployment completed on 2026-09-05 from commit `226e826`: the app container is healthy, the worker and dependencies are healthy, the full suite reported **159 passed** in 42.85s, health and root endpoints returned `HTTP 200`, and the fresh app/worker log scan contained no traceback/error matches.

### 5.4 IMPLEMENTED — Parse trading booleans safely

The live order route previously used Python truthiness for `reduce_only`, which converts the string `"false"` into `True`. The route now accepts native JSON booleans and explicit string equivalents, while rejecting ambiguous values before any broker/product lookup or order placement occurs.

**Risk level:** High safety value, low compatibility risk (valid booleans and common explicit string values are preserved). **Affected modules:** `app/api/v1/trading.py`, `tests/unit/test_delta_trading_signing.py`. **Migration:** none.

**Regression evidence:** Production deployment completed on 2026-09-05 from commit `ebcf986`: the app container is healthy, the worker and dependencies are healthy, the full suite reported **162 passed** in 42.97s, health and root endpoints returned `HTTP 200`, and the fresh app/worker log scan contained no traceback/error matches.

### 5.5 IMPLEMENTED — Reject malformed trading/risk request bodies safely

The risk calculators and live order route now require a JSON object body and return a clear `400` response for arrays, null bodies, and invalid JSON instead of raising an uncaught `TypeError`/`AttributeError`. This protects API reliability at the boundary before any calculation or broker operation begins.

**Risk level:** Medium safety/reliability value, low compatibility risk (valid object requests are unchanged). **Affected modules:** `app/api/v1/risk.py`, `app/api/v1/trading.py`, `tests/integration/test_risk_routes.py`. **Migration:** none.

**Regression evidence:** Production deployment completed on 2026-09-05 from commit `e3cc4ee`: the app container is healthy, the worker and dependencies are healthy, the full suite reported **164 passed** in 44.34s, health and root endpoints returned `HTTP 200`, and the fresh app/worker log scan contained no traceback/error matches.

### 5.6 IMPLEMENTED — Validate position-sizing financial inputs

The risk calculator now rejects non-finite values, non-positive capital/prices/lot sizes, and risk percentages outside `(0, 100]` before calculating units. Volatility sizing also validates ATR and lookback values, preventing negative, infinite, or `NaN` results from reaching the UI or influencing a trade decision.

**Risk level:** High safety value, low compatibility risk (valid calculations and the zero-ATR fallback remain unchanged). **Affected modules:** `app/services/risk/calculator.py`, `tests/unit/test_risk_calculator.py`. **Migration:** none.

**Regression evidence:** Production deployment completed on 2026-09-05 from commit `495d724`: the app container is healthy, the worker and dependencies are healthy, the full suite reported **167 passed** in 44.53s, health and root endpoints returned `HTTP 200`, and the fresh app/worker log scan contained no traceback/error matches.

### 5.7 IMPLEMENTED — Validate portfolio position financial fields

Portfolio add/update routes now require JSON objects, normalize symbols, and validate quantity, buy price, stop loss, and target as finite positive numbers. Optional stop/target values can still be cleared explicitly. This prevents `NaN` or invalid levels from corrupting portfolio valuation and open-risk calculations.

**Risk level:** High safety value, low compatibility risk (valid inputs and explicit clearing remain supported). **Affected modules:** `app/api/v1/portfolio.py`, `tests/integration/test_risk_routes.py`, `tests/unit/test_portfolio_input_validation.py`. **Migration:** none.

**Regression evidence:** Production deployment completed on 2026-09-05 from commit `174862c`: the app container is healthy, the worker and dependencies are healthy, the full suite reported **170 passed** in 45.20s, health and root endpoints returned `HTTP 200`, and the fresh app/worker log scan contained no traceback/error matches.

### 7.7 IMPLEMENTED — Bound OHLCV market-data limits

The authenticated OHLCV endpoint now normalizes invalid `limit` values and clamps them to the existing maximum of 1,000 candles. This avoids 500 responses from malformed query parameters and prevents invalid negative fetch ranges while preserving the default of 200 candles.

**Risk level:** Low (valid requests and the previous maximum are unchanged). **Affected modules:** `app/api/v1/market_data.py`, `tests/unit/test_pagination.py`. **Migration:** none.

**Regression evidence:** Production deployment completed on 2026-09-05 from commit `0846d20`: the app container is healthy, the worker and dependencies are healthy, the full suite reported **171 passed** in 45.59s, health and root endpoints returned `HTTP 200`, and the fresh app/worker log scan contained no traceback/error matches.

### 7.8 IMPLEMENTED — Standardize comparison lookback limits

The multi-asset comparison route now uses the shared bounded pagination helper for its lookback window. Requests are normalized to the existing `20..500` range, malformed values use the 100-bar default, and excessive values cannot expand the market-data fetch beyond 500 bars.

**Risk level:** Low (valid behavior and existing bounds are unchanged). **Affected modules:** `app/api/v1/comparison.py`, `tests/integration/test_comparison_route.py`. **Migration:** none.

**Regression evidence:** Production deployment completed on 2026-09-05 from commit `e31c5a8`: the app container is healthy, the worker and dependencies are healthy, the full suite reported **172 passed** in 45.66s, health and root endpoints returned `HTTP 200`, and the fresh app/worker log scan contained no traceback/error matches.

### 7.9 IMPLEMENTED — Bound signal analytics query filters

Signal listing now normalizes `min_confidence` to a finite `0..100` range, while the per-asset performance endpoint bounds `days` to `1..3650` with a 90-day default. Shared integer/float helpers centralize malformed-input handling and avoid query-time exceptions or misleading future/oversized lookbacks.

**Risk level:** Low (valid requests remain equivalent; only invalid/out-of-range inputs are normalized). **Affected modules:** `app/services/pagination.py`, `app/api/v1/signals.py`, `tests/unit/test_pagination.py`. **Migration:** none.

**Regression evidence:** Production deployment completed on 2026-09-05 from commit `f0c25bc`: the app container is healthy, the worker and dependencies are healthy, the full suite reported **173 passed** in 45.60s, health and root endpoints returned `HTTP 200`, and the fresh app/worker log scan contained no traceback/error matches.

### 6.4 IMPLEMENTED — Add keyboard-accessible dashboard navigation

The primary dashboard shell now provides a skip-to-content link, a labeled navigation landmark, semantic button controls for all six collapsible sidebar groups, and synchronized `aria-expanded` state as groups open/close. The notification bell and toast container also expose explicit accessible semantics. This improves keyboard navigation and makes navigation/state changes discoverable to assistive technology without changing the visual workflow.

**Risk level:** Low (semantic/accessibility markup and state attributes; existing click behavior is preserved). **Affected modules:** `frontend/templates/partials/base.html`, `frontend/static/js/app.js`, `frontend/static/css/main.css`, `tests/unit/test_dashboard_accessibility.py`. **Migration:** none.

**Regression evidence:** Jinja template parsing, JavaScript syntax validation, static accessibility checks, and whitespace validation passed locally. Production deployment completed on 2026-09-05 from commits `6ed1fc2` and `cf40c7c`: the app container is healthy, the worker and dependencies are healthy, the full suite reported **175 passed** in 45.89s, health and root endpoints returned `HTTP 200`, and the fresh app/worker log scan contained no traceback/error matches. Authenticated visual browser verification remains a follow-up because no browser control surface was available in this session.

### 7.10 IMPLEMENTED — Add request correlation and timing logs

The Flask app now preserves a safe inbound `X-Request-ID` or generates one, returns it on every response, and emits a JSON request-completion record for application requests containing the method, path, endpoint, status and duration. Static asset responses keep the correlation header but are excluded from completion logging to avoid log noise. Query strings are intentionally excluded so credentials and other URL parameters are not copied into application logs, while escaped JSON prevents user-controlled paths from creating log-injection lines.

**Risk level:** Low (response header and INFO-level logging only; route behavior and payloads are unchanged). **Affected modules:** `app/__init__.py`, `tests/integration/test_request_observability.py`. **Migration:** none.

**Regression evidence:** The focused integration suite passed locally and in the deployed container (**5 passed**); the full local suite passed with **180 passed** in 97.23s. Production deployment completed on 2026-09-05 from `d6dd16c`: the app, PostgreSQL, Redis and worker were healthy, `/api/v1/system/health` returned `HTTP 200` with the requested correlation ID, the application log contained the expected JSON completion record with duration, and the fresh app/worker error scan was empty. A full integration suite was not run against production because it could mutate live services or data.

### 7.11 IMPLEMENTED — Harden Auto Generate configuration boundaries

Auto Generate save, start and run-once routes now require JSON objects, validate supported markets/timeframes/filters and asset-ID shapes, deduplicate selections, and bound confidence, per-run signals and repeat interval settings. Boolean parsing is explicit, so values such as the string `"false"` are no longer persisted as `True`; malformed or unsupported configuration returns a clear `400` before scheduler or generation work begins, while partial Run Once updates retain their existing semantics.

**Risk level:** Medium reliability and operational-safety value, low compatibility risk (valid UI configuration remains supported; only malformed, unsupported or excessive values are rejected/normalized). **Affected modules:** `app/api/v1/signals.py`, `tests/integration/test_auto_generate_config.py`. **Migration:** none.

**Regression evidence:** Focused Auto Generate integration tests passed locally (**7 passed**); the full local suite passed with **185 passed** in 116.42s. Production deployment completed on 2026-09-05 from `7691d30`: the app, PostgreSQL, Redis and worker were healthy, `/api/v1/system/health` returned `HTTP 200` with the requested correlation ID, the deployed Auto Generate integration module passed (**7 passed**), and the recent app/worker error scan was empty. A full integration suite was not run against production because it could mutate live services or data.

### 7.12 IMPLEMENTED — Harden backtesting request boundaries

The strategy backtest, walk-forward, and live-engine backtest routes now share one validator for JSON/query inputs. It rejects malformed bodies, unsupported timeframes/markets, missing or oversized symbols, non-finite or unsafe capital/cost values, invalid window counts, invalid asset IDs, negative lookbacks, and oversized portfolio limits before database creation or market-data work. Valid symbols are normalized consistently, while valid existing UI defaults remain unchanged.

**Risk level:** Medium reliability and performance value, low compatibility risk (valid UI requests remain supported; malformed or unsafe requests now receive clear `400` responses). **Affected modules:** `app/services/backtest/validation.py`, `app/api/v1/backtesting.py`, `app/api/v1/signals.py`, `tests/unit/test_backtest_request_validation.py`, `tests/integration/test_backtesting_request_boundary.py`. **Migration:** none.

**Regression evidence:** Focused boundary tests passed locally (**24 passed**); the full local suite passed with **209 passed** in 114.61s. Production deployment completed on 2026-09-05 from `953ea6d`: the app, PostgreSQL, Redis and worker were healthy, `/api/v1/system/health` returned `HTTP 200` with the requested correlation ID, the deployed boundary suite passed (**24 passed**), and the ten-minute app/worker error scan was empty. A full integration suite was not run against production because it could mutate live services or data.

### 7.13 IMPLEMENTED — Add observed accuracy context to AI Insights

AI prediction responses now include a bounded historical context for the same asset and timeframe: recent resolved prediction count, correct count, and observed accuracy. The context query is limited to 50 rows and cached for ten minutes, so AI Insights gets useful accountability without adding an expensive query to every model calculation. The AI Insights card now labels this as observed history, shows the sample size, and explicitly indicates when no resolved sample exists; the model confidence score and prediction algorithm are unchanged.

**Risk level:** Low to medium (additive API/UI contract and one indexed, bounded query; no model or database schema change). **Affected modules:** `app/api/v1/predictions.py`, `frontend/templates/dashboard/ai_insights.html`, `tests/unit/test_prediction_history_context.py`, `tests/integration/test_prediction_history_route.py`. **Migration:** none.

**Regression evidence:** Focused API/UI contract tests passed locally (**3 passed**); the full local suite passed with **212 passed** in 116.15s. Production deployment completed on 2026-09-05 from `268ce3e`: the app, PostgreSQL, Redis and worker were healthy, `/api/v1/system/health` returned `HTTP 200` with the requested correlation ID, the deployed prediction-context tests passed (**3 passed**), and the ten-minute app/worker error scan was empty. A full integration suite was not run against production because it could mutate live services or data.

### 7.14 IMPLEMENTED — Reject unsupported AI prediction timeframes

The per-asset AI prediction endpoint now validates its timeframe against the canonical fetchable timeframe registry before checking cache, warming models, fetching candles, or persisting a prediction. Unsupported values no longer fall through the data fetcher’s provider defaults and risk returning a prediction for a different interval under the requested label.

**Risk level:** Medium correctness value, low compatibility risk (all supported `1m` through `1d` timeframes remain available; unsupported intervals now receive a clear `400`). **Affected modules:** `app/api/v1/predictions.py`, `tests/integration/test_prediction_history_route.py`. **Migration:** none.

**Regression evidence:** Focused prediction tests passed locally (**4 passed**); the full local suite passed with **213 passed** in 119.47s. Production deployment completed on 2026-09-05 from `61684f2`: the app, PostgreSQL, Redis and worker were healthy, `/api/v1/system/health` returned `HTTP 200` with `X-Request-ID: prediction-timeframe-20260905`, the deployed prediction tests passed (**4 passed** in 7.31s), and the ten-minute app/worker error scan was empty. A full integration suite was not run against production because it could mutate live services or data.

### 7.15 IMPLEMENTED — Move model-performance aggregation into the database

The model-performance endpoint now calculates overall, timeframe, asset, model, and 30-day trend statistics with SQL aggregates instead of loading every evaluated prediction row into Python. The asset query returns only the top 20 groups needed by the UI, empty summaries are cached consistently, and the prediction evaluator invalidates the summary cache when new outcomes are committed.

**Risk level:** Medium performance and freshness value, low API compatibility risk (response keys and calculations are preserved; no model or schema change). **Affected modules:** `app/api/v1/predictions.py`, `app/tasks/data_tasks.py`, `tests/integration/test_model_performance_route.py`. **Migration:** none.

**Regression evidence:** Focused model-performance tests passed locally (**2 passed**); the full local suite passed with **215 passed** in 122.38s. Production deployment completed on 2026-09-05 from `e0b5d9e`: the app, PostgreSQL, Redis and worker were healthy, `/api/v1/system/health` returned `HTTP 200` with `X-Request-ID: model-performance-20260905`, the deployed model-performance and prediction-context tests passed (**6 passed** in 4.37s), and the ten-minute app/worker error scan was empty. A full integration suite was not run against production because it could mutate live services or data.

### 7.16 IMPLEMENTED — Remove full-history materialization from signal performance

The main signal-performance endpoint no longer loads the complete closed-signal table a second time for confidence calibration. Calibration bands now use conditional SQL aggregation, and timezone-aware hourly bucketing iterates query results in batches of 1,000 rows, preserving the existing dashboard contract while reducing peak Python memory on large histories.

**Risk level:** Medium performance value, low API compatibility risk (existing calculations and null-confidence Weak-bucket behavior are preserved). **Affected modules:** `app/api/v1/signals.py`, `tests/integration/test_signal_performance_queries.py`. **Migration:** none.

**Regression evidence:** Focused signal-performance tests passed locally (**1 passed**); the full local suite passed with **216 passed** in 121.36s. Production deployment completed on 2026-09-05 from `8ed0270`: the app, PostgreSQL, Redis and worker were healthy, `/api/v1/system/health` returned `HTTP 200` with `X-Request-ID: signal-performance-20260905`, the deployed signal and prediction performance tests passed (**7 passed** in 5.04s), and the ten-minute app/worker error scan was empty. A full integration suite was not run against production because it could mutate live services or data.

### 7.17 IMPLEMENTED — Stream signal CSV exports

Live-signal and signal-history CSV exports now stream rows in 500-record batches instead of building the entire file in process memory. Asset details are eager-joined to avoid per-row relationship lookups, while existing filters, columns, filenames, and numeric calculations remain unchanged.

**Risk level:** Medium scalability value, low API compatibility risk (same CSV contract and authentication; no model or schema change). **Affected modules:** `app/api/v1/signals.py`, `tests/integration/test_signal_exports.py`. **Migration:** none.

**Regression evidence:** Focused export tests passed locally (**1 passed**); the full local suite passed with **217 passed** in 188.55s. Production deployment completed on 2026-09-05 from `3e44b0f`: the app, PostgreSQL, Redis and worker were healthy, `/api/v1/system/health` returned `HTTP 200` with `X-Request-ID: signal-export-20260905`, the deployed export and performance tests passed (**8 passed** in 5.98s), and the ten-minute app/worker error scan was empty. A full integration suite was not run against production because it could mutate live services or data.

### 7.18 IMPLEMENTED — Aggregate the legacy per-asset performance endpoint in SQL

The exposed `/signals/performance/by-asset` route now computes overall statistics, asset/timeframe buckets, profit factors, and confidence calibration in database aggregates instead of loading every history row into Python. Optional market filtering is applied in SQL, while the response shape and legacy null-confidence Weak-band behavior remain compatible.

**Risk level:** Medium scalability value, low API compatibility risk (existing keys, calculations, and bounded 50-bucket response are preserved; no model or schema change). **Affected modules:** `app/api/v1/signals.py`, `tests/integration/test_signal_performance_by_asset.py`. **Migration:** none.

**Regression evidence:** Focused per-asset performance tests passed locally (**1 passed**); the full local suite passed with **218 passed** in 153.08s. Production deployment completed on 2026-09-05 from `4a2e978`: the app, PostgreSQL, Redis and worker were healthy, `/api/v1/system/health` returned `HTTP 200` with `X-Request-ID: per-asset-performance-20260905`, the deployed per-asset, signal-performance, export and prediction tests passed (**9 passed** in 6.36s), and the ten-minute app/worker error scan was empty. A full integration suite was not run against production because it could mutate live services or data.

### 7.19 IMPLEMENTED — Rate-limit bulk CSV exports

The live-signal and signal-history export endpoints now apply an endpoint-specific limit of five requests per minute and 30 per hour per caller. This complements streaming by limiting repeated bulk work while keeping normal downloads and all existing CSV filters unchanged.

**Risk level:** Medium abuse-resistance value, low compatibility risk (normal users can continue to export; only repeated bulk requests receive `429`). **Affected modules:** `app/api/v1/signals.py`. **Migration:** none.

**Regression evidence:** Focused export tests passed locally (**1 passed**); the full local suite passed with **218 passed** in 89.83s. Production deployment completed on 2026-09-05 from `1396e07`: the app, PostgreSQL, Redis and worker were healthy, `/api/v1/system/health` returned `HTTP 200` with `X-Request-ID: csv-rate-limit-20260905`, the deployed export, performance and prediction tests passed (**9 passed** in 6.62s), and the ten-minute app/worker error scan was empty. A full integration suite was not run against production because it could mutate live services or data.

### 7.20 IMPLEMENTED — Restore Terminal live-read data-quality persistence

The data-quality persistence change for generated signals also passed data_quality into Terminal LiveReadLog construction, but the live-read model and database schema did not yet have that column. Because the logging helper intentionally catches persistence failures to keep the Terminal responsive, every new BUY/SELL live-read log silently rolled back. The ORM model, serializer, SQLite fallback migration, and Alembic migration now agree, so live-read context is persisted without changing the preview or outcome rules.

**Risk level:** High auditability value, low compatibility risk (nullable additive column; existing rows and live-read response behavior remain valid). **Affected modules:** app/models/live_read_log.py, app/__init__.py, migrations/versions/4c8d9e0f1a2b_add_data_quality_to_live_read_logs.py, tests/unit/test_live_read_log_contract.py. **Migration:** required; the application startup migration runner applies it automatically in the deployed topology.

**Regression evidence:** The focused persistence and Terminal freeze tests passed locally (**5 passed**); the full local suite passed with **219 passed** in 93.27s. Production deployment completed on 2026-09-05 from e7353ba: Alembic reported 4c8d9e0f1a2b (head), the app, PostgreSQL, Redis and worker were healthy, the health endpoint returned HTTP 200 with request ID live-read-quality-20260905, the deployed persistence, Terminal freeze, export, performance and prediction tests passed (**14 passed** in 8.68s), and the ten-minute app/worker error scan contained no app error matches. A full integration suite was not run against production because it could mutate live services or data.

### 7.21 IMPLEMENTED — Serialize PostgreSQL startup migrations

The split Gunicorn web tier can initialize several workers concurrently. Alembic startup migrations now take a PostgreSQL session advisory lock on the same connection used for the upgrade, preventing duplicate-column races and fallback warnings when multiple workers start together. SQLite and offline migration behavior is unchanged, and the lock is released even when an upgrade fails.

**Risk level:** High deployment-reliability value, low runtime compatibility risk (migration startup only; no request or trading behavior changes). **Affected modules:** migrations/env.py. **Migration:** none beyond the existing Alembic revisions.

**Regression evidence:** Migration syntax, Terminal persistence/freeze tests (**5 passed**), and the full local suite (**219 passed** in 104.65s) passed. Production deployment completed on 2026-09-05 from 2555882: all services were healthy, the deployed Alembic revision remained 4c8d9e0f1a2b (head), the health endpoint returned HTTP 200 with request ID migration-lock-20260905, the focused deployed suite passed (**14 passed** in 8.63s), and a fresh app/worker log scan had no migration fallback, duplicate-column, traceback, or error output. A full integration suite was not run against production because it could mutate live services or data.

### 7.22 IMPLEMENTED — Resolve stale Terminal live reads as neutral expiries

Terminal live-read logs now receive an expires_at value from the same timeframe windows used by the signal engine. A worker job marks timed-out open reads as an explicit expired neutral outcome, invalidates the cached performance summary, and preserves target3 as the deliberately stricter win bar. The performance API and card now expose expired-neutral counts, completed denominators, and open reads still inside their valid window, so stale cache replacement cannot silently improve the displayed win rate.

**Risk level:** High measurement-integrity value, low compatibility risk (additive nullable column/API fields and an explicit neutral outcome; existing target3 win/loss behavior remains unchanged). **Affected modules:** app/models/live_read_log.py, app/api/v1/signals.py, app/tasks/data_tasks.py, app/__init__.py, frontend/templates/dashboard/performance.html, migrations/versions/5d9e0f1a2b3c_add_expiry_to_live_read_logs.py, tests/unit/test_live_read_log_contract.py. **Migration:** required; the migration backfills expiry timestamps for existing rows using their stored timeframe.

**Regression evidence:** Expiry, persistence, Terminal freeze and signal-performance tests passed locally (**7 passed**); the full local suite passed with **220 passed** in 139.05s. Production deployment completed on 2026-09-05 from `e87ac77`: Alembic reported `5d9e0f1a2b3c (head)`, all 1,276 existing live-read rows were backfilled with expiry timestamps and 0 remained missing one, the app, PostgreSQL, Redis and worker were healthy, `/api/v1/system/health` returned `HTTP 200` with `X-Request-ID: live-read-expiry-20260905`, the deployed persistence, expiry, Terminal freeze, export, performance and prediction tests passed (**15 passed** in 9.31s), the worker scheduler included `expire_live_read_logs`, and the fresh app/worker error scan had no migration fallback, duplicate-column, traceback, critical or error output. A full integration suite was not run against production because it could mutate live services or data.

### 7.23 IMPLEMENTED — Aggregate legacy history statistics in SQL

The cached `/signals/history-stats` endpoint no longer materializes the entire `SignalHistory` table in Python. Overall totals, win/loss/neutral counts, average PnL, profit factor, timeframe, market, signal-type, confidence-band, and expiry what-if metrics are now computed with bounded database aggregate queries, while the optional `rows=` compatibility path remains available for existing internal callers.

**Risk level:** Medium scalability value, low API compatibility risk (existing response keys and calculations are preserved; no model or schema change). **Affected modules:** `app/services/backtest/analyzer.py`, `app/api/v1/signals.py`, `tests/unit/test_history_analyzer_sql.py`. **Migration:** none.

**Regression evidence:** The SQL history contract, authenticated route, and related performance/export route tests passed locally (**6 passed**); the full local suite passed with **221 passed** in 114.77s. Production deployment completed on 2026-09-06 from `166ecae`: the app, PostgreSQL, Redis and worker were healthy, `/api/v1/system/health` returned `HTTP 200` with `X-Request-ID: history-sql-route-20260906`, the deployed history, performance, export and prediction tests passed (**6 passed** in 5.72s), and the fresh app/worker error scan had no error, traceback, critical, or exception output. A full integration suite was not run against production because it could mutate live services or data.

### 7.24 IMPLEMENTED — Aggregate journal statistics in SQL

The authenticated `/journal/stats` endpoint no longer loads every journal row and groups it in Python. Overall financial totals, averages, profit factor, emotion, market, and weekday breakdowns now use database aggregates with a portable PostgreSQL/SQLite weekday mapping, preserving the existing JSON contract and `unknown` handling for empty metadata.

**Risk level:** Medium scalability value, low API compatibility risk (existing response keys and calculations are preserved; journal writes, pagination, and tax exports are unchanged; no model or schema change). **Affected modules:** `app/api/v1/journal.py`, `tests/integration/test_journal_stats_aggregate.py`. **Migration:** none.

**Regression evidence:** The journal stats route and adjacent analytics tests passed locally (**5 passed**); the full local suite passed with **222 passed** in 91.68s. Production deployment completed on 2026-09-06 from `af34e87`: the app, PostgreSQL, Redis and worker were healthy, `/api/v1/system/health` returned `HTTP 200` with `X-Request-ID: journal-stats-20260906`, the deployed journal, history, performance, export and prediction tests passed (**7 passed** in 6.25s), and the fresh app/worker error scan had no error, traceback, critical, or exception output. A full integration suite was not run against production because it could mutate live services or data.

### 7.25 IMPLEMENTED — Account for exit slippage on end-of-data backtest closes

The strategy-config backtest engine now includes the exit fill impact when it force-closes an open position at the final candle. Normal target, stop, reversal, timeout, and partial fills already reported entry plus exit slippage; the end-of-data branch incorrectly stored `slippage_cost: 0.0`, understating total slippage and making the cost audit inconsistent for positions still open at the data boundary.

**Risk level:** High measurement-integrity value, low compatibility risk (backtest reporting only; simulated fill prices, capital, commission, and trading behavior are unchanged). **Affected modules:** `app/services/backtesting/engine.py`, `tests/unit/test_backtest_partial_exit_consolidation.py`. **Migration:** none.

**Regression evidence:** Backtest correctness and request-boundary tests passed locally (**44 passed**); the full local suite passed with **223 passed** in 90.65s. Production deployment completed on 2026-09-06 from `f6e2106`: the app, PostgreSQL, Redis and worker were healthy, `/api/v1/system/health` returned `HTTP 200` with `X-Request-ID: forced-close-slippage-20260906`, the deployed backtest correctness and request-boundary tests passed (**44 passed** in 8.31s), and the fresh app/worker error scan had no error, traceback, critical, or exception output. A full integration suite was not run against production because it could mutate live services or data.

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

**Session 7 (performance — frontend GET coalescing and collection pagination, §7.4–7.5):**
- `frontend/static/js/app.js` — coalesces identical concurrent dashboard GET requests without adding stale caching.
- `app/api/v1/news.py`, `app/api/v1/journal.py`, `app/api/v1/notifications.py` — apply shared page and page-size bounds to collection endpoints.

- `docs/IMPROVEMENT_AUDIT.md` — this file.

**Database changes:** none across all six sessions; `Backtest` rows already had the `winning_trades`/`losing_trades`/`equity_curve`/`trades_data` columns, they just weren't being serialized. **API contract changes:** none breaking — `POST /backtesting/run`'s response gained fields (`equity_curve`, `trades_data`, `winning_trades`, `losing_trades`) it was always supposed to return per its own `to_dict()`/`get_backtest()` sibling pattern; no field removed or renamed. Phase 3 adds a new internal gate to `generate_signal()` that can return `None` (no signal) in cases that previously would have produced one — specifically only when data is stale (live path only) or corrupt (both live and backtest) — no existing route, response shape, or subscription rule changed. **No destructive migration. No new credentials or secrets introduced.**
