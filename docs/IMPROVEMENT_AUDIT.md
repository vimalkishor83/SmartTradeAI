# SmartTrade AI — Improvement Audit

**Status:** Living document. Started as Phase 0 of a structured production-hardening pass; updated as each subsequent phase's investigation and fixes land. Every entry below is based on reading the actual code and, where marked, verifying behavior live on the production server — not on the platform's design intent or documentation claims.

**Last updated:** 2026-09-06 (Phase 0 + Phase 1 + Phase 2 + Phase 3 + Phase 4 + Phase 5 initial pass)

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
- **The `confidence_score` shown on every regular, automatically-generated signal is rule-based technical scoring — it is not ML model output.** The real ML ensemble is only invoked by a separate, manual, super-admin-only endpoint (`POST /signals/generate`), which adds a small, explicitly labeled AI boost only when a real calibrated prediction is available. The former automatic `ai=10` placeholder was removed in §7.30 so automatic confidence is no longer inflated by a fabricated model component.
- **A confidence-calibration system already exists** and is more mature than expected: `app/api/v1/signals.py::_confidence_calibration_bands()` buckets closed signals into Weak/Moderate/Strong/Very Strong bands and compares actual vs. expected win rate, rendered as a chart on the main dashboard. Separately, `/model-performance` tracks the AI predictor's own directional accuracy (not bucketed by confidence). **Important nuance for future work**: the calibration chart evaluates the *rule-based* `confidence_score`, which per the point above isn't an ML probability to begin with — worth keeping in mind before extending it further.
- `/ai-insights` (the real ML-ensemble-backed page) now shows bounded observed accuracy context beside the confidence percentage, plus the persisted model version when available; the contract and rollout are recorded in §7.31.

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

### 3.3 Remaining Phase 2 items

- Evidence and counter-evidence are available in the AI Decision Inspector (§6.1), input-quality context is available in AI Insights and the Inspector (§6.3/§7.32), and member agreement is available in AI Insights (§7.33); a dedicated uncertainty presentation remains to be designed.
- Broader model-performance and calibration views remain separate from the per-asset/timeframe observed history now shown on `/ai-insights`; future work should reconcile these scopes without presenting them as interchangeable metrics.
- Whether/how to redesign `_compute_confidence`'s broader weighting remains a product decision; the fabricated automatic AI component itself is removed in §7.30.
- Individual RF/XGBoost/LightGBM bullish outputs and their observed spread are now exposed on AI prediction cards (§7.33); independent long-run evaluation and drift monitoring for each member remain future rigor work.
- Market-regime confidence near AI Insights remains absent; freshness and integrity context is now available on AI prediction cards through §7.32, while signal-level quality is covered by §6.3 and Phase 3.

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
- Signal versioning at the schema level remains future work; read-only position analysis now returns an explicit `analysis_state` and no-signal reason (§7.35) without changing persisted signal behavior.

---

## 6. Phase 5 — AI Decision Inspector: findings and fixes

### 6.1 FOUND & FIXED — Evidence/Counter-Evidence data existed but was never shown

**Root cause:** `SignalEngine.generate_signal()`/`analyze()` already compute and persist a structured, per-factor breakdown of what supported vs. opposed the final call — `reasoning_detail`, a list of `{text, lean, aligned}` (see `SignalEngine._labeled_reasons()`), where `aligned` marks whether that factor's lean agreed with the signal's final direction or was outweighed by something stronger (e.g. a reversal pattern beating a still-bullish EMA trend). This is real, already-computed, already-persisted data (`Signal.reasoning_detail`, a JSON column, included in `Signal.to_dict()` and therefore in every `/signals` API response) — and the server-side `_build_retrospective_note()` used by `/signal-journal` already reads it. But the AI Decision Inspector (`frontend/static/js/pages/dashboard.js::loadInspector()`) never used it at all: it only showed a fixed 4-item checklist (score-vs-threshold pass/fail, no actual reasons) and a "Confidence Factors" bar chart. Counter-evidence in particular — a factor that pointed the other way but lost — was silently dropped everywhere in the UI even though it was sitting in the API response the whole time. This is exactly the "Evidence/Counter-Evidence" gap flagged as not-yet-built in §3.3 and §4.1 of this audit.

**Fix:** `loadInspector()` now splits `s.reasoning_detail` on its existing `aligned` flag into two new sections — "Evidence Supporting {BUY/SELL}" (aligned factors, green check icons, reusing the existing `.insp-check`/`.insp-checks` styling) and "Counter-Evidence (outweighed)" (non-aligned factors, only rendered when at least one exists — most signals have none). No new backend work was needed; this is a pure frontend addition surfacing data the engine was already producing.

**Risk level:** Low (additive UI only, reuses existing CSS classes, no calculation/API changes). **Affected modules:** `frontend/static/js/pages/dashboard.js`. **Migration:** none. **Tests:** none added — no test infrastructure exists for this vanilla-JS dashboard file (confirmed: no frontend build/test pipeline in this repo), consistent with how the Phase 2 §3.2 frontend-only fix was handled; existing 148 backend tests confirmed passing unchanged.

**Verified live** (production, disposable test account, deleted after): fetched a real live `AVAXUSDT` BUY signal via the actual `/api/v1/signals/` endpoint and called `loadInspector()` with it directly in the browser — confirmed "Evidence Supporting BUY" rendered all 8 real, live reasoning factors ("EMA9>EMA21 (uptrend)", "Golden cross zone", "Price above VWAP", "SuperTrend bullish", "Price above Ichimoku cloud", "RSI bullish zone (60)", "MACD bullish crossover", "Volume in line with average") with correct green-check styling; confirmed the Counter-Evidence section correctly does not render when a signal has none (this one had none); confirmed the rest of the Inspector (entry/stop/targets, checklist, warnings, Confidence Factors) still renders correctly alongside the new sections.

### 6.2 Remaining Phase 5 items (not done in this pass)

- Confidence-matched historical-accuracy context alongside the Inspector's confidence % remains future work; §7.34 now shows same-asset/timeframe closed history with explicit decisive and neutral counts.
- Data-quality status is now surfaced in the Inspector (§6.3); the same contract is also persisted on AI prediction cards in §7.32.
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

This audit and the fixes above cover Phase 0 (discovery), the highest-priority item of Phase 1 (win-rate correctness + its immediately adjacent display bugs, including the partial-TP consolidation fix), the strategy backtest cost and risk-metric audit, signal-lifecycle provenance, removal of the fabricated automatic AI confidence component, one concrete, well-scoped Phase 2 item (fabricated per-model attribution), the core Phase 3 item (the data quality gate), one concrete Phase 4 item (the LiveReadLog non-comparable-accuracy-claim fix), and one concrete Phase 5 item (Evidence/Counter-Evidence in the AI Decision Inspector). The full spec's remaining phases are substantial, multi-week-scale work and have **not** been started:

- Phase 1 (remainder): remaining high-impact calculation decisions not covered by the strategy-config engine audit.
- Phase 2 (remainder): broader confidence weighting and AI accountability items in §3.3 above.
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

### 7.26 IMPLEMENTED — Stamp backtest reproducibility metadata

Successful strategy-config, walk-forward, and live-signal backtest results now expose a common provenance contract: engine version, explicit model scope, canonical configuration fingerprint, ordered OHLCV dataset fingerprint, candle count, and dataset bounds. Persisted strategy backtests store the same fields through an additive migration and return the saved backtest ID, while deterministic rule-based strategies correctly report `model_version: not_applicable` rather than implying an ML model produced the result.

**Risk level:** High auditability value, low runtime compatibility risk (additive nullable columns and response metadata; no strategy, fill, or metric behavior changes). **Affected modules:** `app/services/backtesting/reproducibility.py`, `app/services/backtesting/engine.py`, `app/services/backtesting/walk_forward.py`, `app/services/backtest/runner.py`, `app/models/backtest.py`, `app/api/v1/backtesting.py`, `app/__init__.py`, `migrations/versions/6e0f1a2b3c4d_add_backtest_reproducibility_metadata.py`, `tests/unit/test_backtest_reproducibility.py`, `tests/integration/test_backtest_metadata_route.py`. **Migration:** required; additive nullable columns are applied automatically at startup.

**Regression evidence:** Reproducibility, persistence, walk-forward, partial-exit, and request-boundary tests passed locally (**26 passed**); the full local suite passed with **228 passed** in 93.29s. Production deployment completed on 2026-09-06 from `45e8a5f`: Alembic reported `6e0f1a2b3c4d (head)`, the app, PostgreSQL, Redis and worker were healthy, `/api/v1/system/health` returned `HTTP 200` with `X-Request-ID: backtest-repro-20260906`, the deployed provenance, backtest correctness, walk-forward, and request-boundary tests passed (**49 passed** in 9.60s), and the fresh app/worker error scan had no application error, traceback, critical, exception, migration fallback, or duplicate-column output. The standalone Flask CLI inspection still emits the previously observed Eventlet context warnings, but they are outside the Gunicorn app/worker logs and did not prevent the migration from reaching head. A full integration suite was not run against production because it could mutate live services or data.

### 7.27 IMPLEMENTED — Model explicit bid/ask spread in strategy backtests

Strategy-config backtests now accept an optional full-spread assumption, defaulting to zero for backward compatibility. The engine applies half the spread adversely on every entry, target, stop, reversal, timeout, partial, and end-of-data fill, reports `total_spread` alongside commission and slippage, and includes the assumption in the reproducibility fingerprint. Partial exits prorate entry friction across legs so consolidated trade metrics do not double-count entry costs. The Backtesting UI exposes the three cost assumptions for non-live strategies and shows the configured model plus realized friction beside the results; the live-signal walk-forward path remains unchanged because it uses a different execution model.

**Risk level:** High measurement-integrity value, low compatibility risk (optional input defaults to zero; additive result fields and migration; existing default backtests keep their prior fill behavior). **Affected modules:** `app/services/backtest/validation.py`, `app/services/backtesting/engine.py`, `app/services/backtesting/walk_forward.py`, `app/services/backtesting/reproducibility.py`, `app/api/v1/backtesting.py`, `app/models/backtest.py`, `app/__init__.py`, `frontend/templates/dashboard/backtesting.html`, `migrations/versions/7f1a2b3c4d5e_add_backtest_spread_metrics.py`, `tests/unit/test_backtest_partial_exit_consolidation.py`, `tests/unit/test_backtest_request_validation.py`, `tests/integration/test_backtesting_request_boundary.py`, `tests/integration/test_backtest_metadata_route.py`. **Migration:** required; additive spread metrics are applied automatically at startup.

**Regression evidence:** Spread fill direction, partial-exit allocation, request validation, route boundaries, persistence, and provenance tests passed locally (**37 passed**); the full local suite passed with **231 passed** in 134.61s. Production deployment completed on 2026-09-06 from `e7d1a6e`: Alembic reported `7f1a2b3c4d5e (head)`, the app, PostgreSQL, Redis and worker were healthy, `/api/v1/system/health` returned `HTTP 200` with `X-Request-ID: backtest-spread-20260906`, the safe deployed backtest unit subset passed (**29 passed** in 5.18s), and the fresh app/worker error scan had no application error, traceback, critical, exception, migration fallback, or duplicate-column output. The standalone Flask CLI inspection still emits the previously observed Eventlet context warnings, but they are outside the Gunicorn app/worker logs and did not prevent the migration from reaching head. A full integration suite was not run against production because it could mutate live services or data.

### 7.28 IMPLEMENTED — Correct annualized risk ratios and add recovery factor

The strategy-config backtest engine no longer annualizes per-trade percentage returns with a per-candle factor, which mixed incompatible observation frequencies and could materially inflate Sharpe and Sortino. Both ratios now use realized per-bar equity returns sampled at the input candle frequency; Sortino uses zero as its explicit target and downside RMS across the full return sample. The engine also reports a recovery factor (`net profit / maximum drawdown in account currency`), with an explicit `999` cap only for positive results with no observed drawdown. The field is persisted and shown in the strategy backtest UI; the live-signal walk-forward engine remains R-based and does not claim unsupported risk ratios.

**Risk level:** High measurement-integrity value, medium compatibility impact (existing Sharpe/Sortino values may change because the prior units were incorrect; recovery factor is additive and capped for non-finite no-drawdown cases). **Affected modules:** `app/services/backtesting/engine.py`, `app/models/backtest.py`, `app/__init__.py`, `frontend/templates/dashboard/backtesting.html`, `migrations/versions/8a2b3c4d5e6f_add_backtest_recovery_factor.py`, `tests/unit/test_backtest_risk_metrics.py`. **Migration:** required; the additive nullable recovery metric is applied automatically at startup.

**Regression evidence:** Equity-frequency Sharpe/Sortino, downside deviation, drawdown recovery, no-drawdown handling, backtest persistence, partial-exit, and request-boundary tests passed locally (**21 focused tests**); the full local suite passed with **234 passed** in 134.14s. Production deployment completed on 2026-09-06 from `082559e`: Alembic reported `8a2b3c4d5e6f (head)`, the app, PostgreSQL, Redis and worker were healthy, `/api/v1/system/health` returned `HTTP 200` with `X-Request-ID: backtest-risk-20260906`, the safe deployed backtest metric subset passed (**32 passed** in 5.18s), and the fresh app/worker error scan had no application error, traceback, critical, exception, migration fallback, or duplicate-column output. The standalone Flask CLI inspection still emits the previously observed Eventlet context warnings, but they are outside the Gunicorn app/worker logs and did not prevent the migration from reaching head. A full integration suite was not run against production because it could mutate live services or data.

### 7.29 IMPLEMENTED — Stamp live signal reproducibility metadata

Persisted signals now record whether they came from the automatic scheduler or the manual super-admin endpoint, the version of the signal engine, the AI model version when a real calibrated ensemble result was used, and the exact OHLCV frame's candle count, UTC bounds and SHA-256 fingerprint. Rule-based signals explicitly use `model_version: not_applicable`; a predictor neutral fallback no longer changes the manual signal score or claims an AI model was used. The metadata is additive and nullable for legacy rows. The Decision Inspector surfaces the source, model/scoring mode, candle count and shortened fingerprint, and labels the explanation as signal qualification rather than implying every signal was chosen by AI. Backtest calls do not hash each candle window in the hot path and do not create `Signal` rows, so backtest-only calculations remain separate from live-alert provenance.

**Risk level:** Medium auditability value, low runtime compatibility risk (additive nullable columns and response metadata; provenance hashing occurs only after a signal has passed generation and never blocks storage). **Affected modules:** `app/services/signals/provenance.py`, `app/services/ai/predictor.py`, `app/models/signal.py`, `app/api/v1/signals.py`, `app/tasks/signal_tasks.py`, `app/__init__.py`, `frontend/static/js/pages/dashboard.js`, `migrations/versions/9b3c4d5e6f7a_add_signal_reproducibility_metadata.py`, `tests/unit/test_signal_provenance.py`, `tests/unit/test_signal_quality_contract.py`. **Migration:** required; additive nullable signal provenance columns are applied automatically at startup.

**Regression evidence:** Focused local provenance/serialization tests passed (**5 passed**); production verification completed on 2026-09-06 from `31674bc`: Alembic reported `9b3c4d5e6f7a (head)`, the app health endpoint returned `HTTP 200` with `X-Request-ID: signal-provenance-20260906`, app/db/Redis/worker services were healthy or running, and the safe deployed provenance, quality and backtest-risk subset passed (**8 passed**). The standalone Flask CLI inspection still emits the previously observed Eventlet context warnings, but they are outside the Gunicorn app/worker logs and did not prevent the migration from reaching head. A full production integration suite was not run because it could mutate live services or data.

### 7.30 IMPLEMENTED — Remove fabricated automatic AI confidence bonus

Automatic signal generation now uses only the rule-based trend, momentum, volume and pattern components. The legacy `ai_score=10` value was a hardcoded placeholder even though the scheduled pipeline never invoked the ML predictor, so it increased `confidence_score` without evidence and was also displayed as an AI bar on the Signals page. The field remains in the response for compatibility but is now zero for automatic signals. Manual super-admin generation retains its separate AI boost only when the predictor returns a real calibrated ensemble version; neutral predictor fallbacks no longer change the score.

**Risk level:** High honesty and measurement-integrity value, medium behavioral impact (some automatic signals near the threshold will no longer qualify; this intentionally favors fewer evidence-backed alerts over inflated signal volume). **Affected modules:** `app/services/signals/engine.py`, `frontend/templates/dashboard/signals.html`, `tests/unit/test_signal_engine_confidence.py`, `tests/unit/test_signal_provenance.py`, `app/api/v1/signals.py`, `app/services/ai/predictor.py`. **Migration:** none.

**Regression evidence:** Local targeted signal-confidence, provenance and serialization tests passed (**7 passed**), and the full local suite passed with **240 passed** in 132.27s; JavaScript syntax/whitespace validation passed. Production app verification completed on 2026-09-06 from `3b9cb54` after the backend provenance release: the app health endpoint returned `HTTP 200` with `X-Request-ID: signal-provenance-ui-20260906`, the app was healthy, and the deployed Signals page source no longer contains the fabricated AI bar. No live signal was manually generated for verification because that endpoint writes production data and can invoke real model training.

### 7.31 IMPLEMENTED — Persist AI prediction model versions and retire fallback history pollution

AI predictions now persist the calibrated predictor version (`ensemble-calibrated-v1`) through the direct endpoint, batch AI summary, and scheduled prewarm writer. A shared prediction-record builder removes the former field-mapping duplication across those writers. Neutral or short-data predictor fallbacks remain available to the UI but are no longer written into validation history as trained-model predictions. The AI summary Redis key was moved to `ai_summary_all:v2` in this slice, then to `v3` in §7.32, and to `v4` in §7.33 as the payload gained data-quality and member-output metadata, so stale payloads cannot hide the current contract. AI Insights now shows the model name, version availability, and an explicit reminder that probabilities are model outputs rather than guaranteed outcomes; legacy rows are labeled as version-unavailable rather than being rewritten with an invented version.

**Risk level:** High auditability and measurement-integrity value, low compatibility risk (one additive nullable prediction column, additive response metadata, and an explicit 202 warming-up response for a predictor fallback). **Affected modules:** `app/models/prediction.py`, `app/services/ai/prediction_records.py`, `app/api/v1/predictions.py`, `app/api/v1/market_data.py`, `app/tasks/data_tasks.py`, `app/__init__.py`, `migrations/versions/ac4d5e6f7a8b_add_prediction_model_version.py`, `frontend/templates/dashboard/ai_insights.html`, `tests/unit/test_prediction_model_version.py`. **Migration:** required; the additive nullable prediction column is applied automatically at startup.

**Regression evidence:** Focused model-version, history-context, and authenticated prediction-route tests passed (**6 passed**); Python compilation and whitespace validation passed; the full local suite passed with **242 passed** in 127.26s. Production deployment completed on 2026-09-06 from `0a65650` via the authorized server checkout: Alembic reported `ac4d5e6f7a8b (head)`, the app/worker and dependencies were healthy/running, and the health endpoint returned `HTTP 200`. The safe deployed model-version and history-context unit tests passed (**4 passed**); the standalone Flask CLI inspection still emits the previously observed Eventlet context warnings outside the app/worker logs. A full production integration suite is intentionally not run because prediction generation and other integration paths can mutate live services or data.

### 7.32 IMPLEMENTED — Persist AI input data quality and surface it in AI Insights

Each newly computed AI prediction now snapshots the existing data-quality contract at the persistence boundary: status, candle count, expected interval, normalized last-candle timestamp, age, issues and hard-invalid state. The same context is returned by the direct prediction endpoint and both AI summary paths. This avoids treating a high model confidence as sufficient on its own when candles are stale, gapped or otherwise invalid. Legacy prediction rows remain compatible with a clearly unavailable quality state, and the summary cache moved to `ai_summary_all:v3` to invalidate payloads created before this context existed. AI Insights renders a compact green/yellow/red input-quality indicator with candle age and the first relevant issue; it does not convert quality into a fabricated confidence adjustment.

**Risk level:** High decision-context value, low compatibility risk (one additive nullable JSON column, additive response metadata, and no change to model probabilities or signal thresholds). **Affected modules:** `app/models/prediction.py`, `app/services/ai/prediction_records.py`, `app/api/v1/predictions.py`, `app/api/v1/market_data.py`, `app/tasks/data_tasks.py`, `app/__init__.py`, `migrations/versions/bd5e6f7a8b9c_add_prediction_data_quality.py`, `frontend/templates/dashboard/ai_insights.html`, `tests/unit/test_prediction_model_version.py`, `tests/unit/test_data_quality.py`. **Migration:** required; the additive nullable prediction quality column is applied automatically at startup.

**Regression evidence:** Focused prediction-quality, data-quality, and history-context tests passed (**28 passed**); Python compilation and whitespace validation passed. Production deployment completed on 2026-09-06 from `d13869a` via the authorized server checkout: Alembic reported `bd5e6f7a8b9c (head)`, the app/worker and PostgreSQL/Redis dependencies were healthy/running, and the health endpoint returned `HTTP 200` with `X-Request-ID: ai-quality-context-20260906`. The same isolated unit set passed in the app container (**28 passed**), and the fresh app/worker log scan contained no traceback, critical, exception, duplicate-column, or migration-fallback matches. A full production integration suite is intentionally not run because prediction generation and other integration paths can mutate live services or data.

### 7.33 IMPLEMENTED — Expose real ensemble member outputs and agreement spread

The AI predictor now retains each available RF, XGBoost and LightGBM `predict_proba()` bullish output instead of discarding the member-level values after averaging. The prediction cache stores those outputs with the ensemble probability, and persisted/API records expose them as `model_outputs`. AI Insights renders the available member values and their actual percentage-point spread as decision context; it no longer uses fabricated scores or names. If only one trained member is available the model is labeled `partial-ensemble`; if no trained member is available the heuristic fallback is labeled non-ML and carries no model version. The summary cache moved to `ai_summary_all:v4` to invalidate payloads created before member outputs existed.

**Risk level:** High transparency value, low calculation risk (the ensemble mean and thresholds are unchanged; only discarded real outputs are retained and displayed). **Affected modules:** `app/services/ai/predictor.py`, `app/models/prediction.py`, `app/services/ai/prediction_records.py`, `app/api/v1/predictions.py`, `app/api/v1/market_data.py`, `app/tasks/data_tasks.py`, `app/__init__.py`, `migrations/versions/c6f7a8b9c0d1_add_prediction_model_outputs.py`, `frontend/templates/dashboard/ai_insights.html`, `tests/unit/test_prediction_model_outputs.py`, `tests/unit/test_prediction_model_version.py`. **Migration:** required; the additive nullable member-output JSON column is applied automatically at startup.

**Regression evidence:** Focused member-output, model-version, and provenance tests passed (**7 passed**); Python compilation and whitespace validation passed. Production deployment verification is pending for this slice; the safe plan is Alembic head inspection, health/compose checks, source verification, isolated unit tests in the app container, and a non-mutating log scan. A full production integration suite is intentionally not run because prediction generation and other integration paths can mutate live services or data.

### 7.34 IMPLEMENTED — Add same-asset/timeframe history to the Decision Inspector

Active signal list and detail responses now include grouped historical context for the exact asset and timeframe being inspected: total resolved records, decisive sample size, wins, losses, neutral expiries, accuracy and average P&L. Accuracy is explicitly calculated from wins divided by wins plus losses; neutral expiries remain visible but do not inflate or depress that decisive accuracy percentage. The dashboard Inspector renders this beside data quality, regime and provenance and labels it as historical context rather than a forecast. The grouped query avoids an N+1 database lookup when the active signal page contains multiple rows.

**Risk level:** Low (read-only additive API metadata and UI context; no signal selection, confidence, execution or outcome calculation changed). **Affected modules:** `app/api/v1/signals.py`, `frontend/static/js/pages/dashboard.js`, `tests/integration/test_signal_history_context.py`. **Migration:** none.

**Regression evidence:** Focused history-context and prediction-context integration tests passed (**4 passed**), JavaScript syntax validation, Python compilation and whitespace validation passed, and the full local regression suite passed (**249 passed**). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is health/compose/source checks plus isolated tests only, not the mutating integration suite.

### 7.35 IMPLEMENTED — Return explicit analysis state and no-signal reasons

The read-only signal-analysis pipeline now distinguishes `SIGNAL`, `NO_SIGNAL` and `UNAVAILABLE` through an additive `analysis_state` field. HOLD reads and directional reads below the 70% auto-alert threshold carry stable reason codes and user-facing explanations, while market-closed, insufficient-data, indicator-failure, volatility-blocked and market-data-unavailable responses carry `UNAVAILABLE` context. Terminal and asset-analysis UI surfaces now render the actual reason instead of using one generic “no setup” message. Signal thresholds, gating decisions, persistence and execution behavior are unchanged.

**Risk level:** Low (additive read-response metadata and UI copy; no scoring or trade lifecycle changes). **Affected modules:** `app/services/signals/engine.py`, `app/api/v1/signals.py`, `frontend/templates/markets/terminal.html`, `frontend/templates/asset/detail.html`, `tests/unit/test_signal_analysis_state.py`. **Migration:** none.

**Regression evidence:** Focused state, confidence and terminal lifecycle tests passed (**9 passed**), dashboard JavaScript syntax validation, Python compilation and whitespace validation passed, and the full local regression suite passed (**249 passed**). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is health/compose/source checks plus isolated tests only, not the mutating integration suite.

### 7.36 IMPLEMENTED — Keep recent AI prediction reads fresh and newest-first

Direct prediction reads, batch AI summaries and scheduled cache prewarming now order recent prediction rows newest-first and retain the first row per asset/timeframe. This prevents an older row from overwriting the current prediction when several records fall inside the freshness window. The expired-prediction evaluator also invalidates the matching historical-context cache after outcomes are committed, so observed accuracy reflects newly evaluated results instead of waiting for the cache TTL.

**Risk level:** Low (query ordering and targeted cache invalidation only; no prediction calculation, threshold or evaluation semantics changed). **Affected modules:** `app/api/v1/predictions.py`, `app/api/v1/market_data.py`, `app/tasks/data_tasks.py`, `tests/integration/test_prediction_history_route.py`, `tests/unit/test_prediction_cache_freshness.py`. **Migration:** none.

**Regression evidence:** Focused freshness tests passed (**4 passed**), Python compilation and whitespace validation passed, and the full local regression suite passed (**251 passed** in 129.83s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is health/compose/source checks plus isolated tests only, not the mutating integration suite.

### 7.37 IMPLEMENTED — Make model-performance accountability explicit

The model-performance endpoint now reports evaluated-row coverage separately from reproducible model-version coverage and exposes accuracy grouped by model version. This preserves the existing overall and model-family aggregates for continuity while preventing legacy rows with missing provenance from looking equivalent to current versioned output. The UI adds an evaluation-scope panel, version-level table and explicit legacy-row label. The trend chart now keeps its canvas mounted when showing an empty state, so a later refresh can render new data correctly, and database-provided labels are escaped before table insertion.

**Risk level:** Low to medium (additive SQL aggregates and reporting/UI hardening; no prediction, signal, threshold or outcome logic changed). **Affected modules:** `app/api/v1/predictions.py`, `frontend/templates/dashboard/model_performance.html`, `tests/integration/test_model_performance_route.py`. **Migration:** none.

**Regression evidence:** Focused model-performance tests passed (**2 passed**), Python compilation, JavaScript syntax validation and whitespace checks passed, and the full local regression suite passed (**251 passed** in 131.25s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is health/compose/source checks plus isolated tests only, not the mutating integration suite.

### 7.38 IMPLEMENTED — Surface provider verification freshness in Admin

API configuration responses now include a side-effect-free provider-health contract derived from the existing status, connection status, refresh interval and last successful connection test. Admins can distinguish recently verified, stale, untested, failed and intentionally paused configurations without triggering network calls. The API-config list also serializes each row once instead of repeating the same conversion for the flat and grouped payloads. The admin UI adds a verification summary, row-level health labels and an explicit caveat that this is last-test evidence rather than continuous provider telemetry; database-backed labels and test-log content are escaped before insertion.

**Risk level:** Low (read-only derived metadata and admin rendering hardening; no credentials, provider calls, trading or fetch behavior changed). **Affected modules:** `app/services/provider_health.py`, `app/models/api_config.py`, `app/api/v1/admin.py`, `frontend/templates/admin/api_configs.html`, `tests/unit/test_provider_health.py`. **Migration:** none.

**Regression evidence:** Provider-health tests passed (**6 passed**), Python compilation, JavaScript syntax validation and whitespace checks passed, and the full local regression suite passed (**257 passed** in 134.14s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is health/compose/source checks plus isolated tests only, not the mutating integration suite.

### 7.39 IMPLEMENTED — Keep AI prediction requests non-blocking when models are partial

The API uses `has_ready_model()` to avoid training inside a user request. That check previously returned ready when any one of the RF, XGBoost or LightGBM files was fresh, while `predict()` required every installed member before it could use inference-only mode. A partially warmed ensemble could therefore enter the request path and train missing members, contradicting the endpoint's fast warming-up contract. Readiness now delegates to the same all-installed-members check used by prediction, while retaining the existing in-process cache fast path.

**Risk level:** Medium performance and reliability value, low decision risk (no model parameters, probabilities, thresholds or labels changed). **Affected modules:** `app/services/ai/predictor.py`, `tests/unit/test_predictor_readiness.py`. **Migration:** none.

**Regression evidence:** Focused predictor readiness/member-output/model-version tests passed (**5 passed**), Python compilation and whitespace validation passed, and the full local regression suite passed (**258 passed** in 125.64s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.40 IMPLEMENTED — Purge triple-barrier label horizons before AI calibration

The chronological calibration splitter now removes a 10-bar gap, matching the maximum triple-barrier label horizon, between the final training row and the first validation row. Previously, a training label near that boundary could inspect future OHLC bars that belonged to the validation period, making calibration evidence optimistic. The split remains chronological, rolling and last-row-safe; only the training/calibration boundary changed.

**Risk level:** High model-evaluation integrity value, low runtime/API risk (training uses fewer boundary rows; inference thresholds and output contracts are unchanged). **Affected modules:** `app/services/ai/predictor.py`, `tests/unit/test_predictor_splits.py`. **Migration:** none.

**Regression evidence:** Focused split, readiness, member-output and model-version tests passed (**7 passed**), Python compilation and whitespace validation passed, and the full local regression suite passed (**260 passed** in 121.59s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.41 IMPLEMENTED — Version AI artifacts with the training contract

The calibrated predictor contract is now `ensemble-calibrated-v2`, and the model artifact hash includes that version. Existing v1 pickles therefore cannot be silently reused after the purged calibration change; the next background prewarm creates fresh v2 artifacts before they can be persisted as new predictions. This keeps stored model provenance aligned with the actual feature, label and calibration semantics while leaving the probability threshold and response shape unchanged.

**Risk level:** High model-provenance value, medium rollout/runtime impact (old artifacts are intentionally ignored and require a fresh background training pass; user requests remain non-blocking and return warming-up status until ready). **Affected modules:** `app/services/ai/predictor.py`, `tests/unit/test_prediction_model_outputs.py`. **Migration:** none; old artifact files are left untouched and simply no longer selected by the versioned key.

**Regression evidence:** Focused predictor contract tests passed (**8 passed**), Python compilation and whitespace validation passed, and the full local regression suite passed (**261 passed** in 104.36s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.42 IMPLEMENTED — Validate admin API-configuration writes at the boundary

Admin provider-configuration create/update payloads now share one validator. It normalizes bounded text and numeric values, requires supported market/provider combinations, accepts only explicit boolean representations, and restricts auth types and statuses before any database mutation. A market change is rejected when the existing provider would become incompatible, preventing an invalid half-updated configuration. Valid UI payloads remain compatible; credentials are still written only when supplied.

**Risk level:** High operational-safety value, low compatibility risk (valid configuration fields and defaults are preserved; malformed values now receive `400` instead of a server error or ambiguous persistence). **Affected modules:** `app/services/api_config_validation.py`, `app/api/v1/admin.py`, `tests/unit/test_api_config_validation.py`. **Migration:** none.

**Regression evidence:** Focused validation tests passed (**14 passed**), Python compilation and whitespace validation passed, and the full local regression suite passed (**275 passed** in 105.75s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.43 IMPLEMENTED — Show neutral and decisive AI evaluation outcomes

The model-performance response now reports the evaluated actual-outcome mix (bullish, bearish, neutral and unknown) plus a separate decisive directional accuracy that excludes neutral outcomes. The existing overall `was_correct` accuracy remains unchanged for continuity, while the UI explicitly explains that neutral outcomes may be counted by the legacy evaluator contract; this prevents a strong-looking aggregate from hiding how much of the sample was non-directional.

**Risk level:** High accountability value, low runtime/API risk (two additive response objects and one SQL aggregate; no prediction evaluation semantics changed). **Affected modules:** `app/api/v1/predictions.py`, `frontend/templates/dashboard/model_performance.html`, `tests/integration/test_model_performance_route.py`. **Migration:** none.

**Regression evidence:** Focused model-performance tests passed (**2 passed**), Python compilation, JavaScript syntax and whitespace validation passed, and the full local regression suite passed (**275 passed** in 109.63s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.44 IMPLEMENTED — Publish AI model artifacts atomically

AI model saves now serialize to a same-directory temporary file and publish with `os.replace()` only after serialization completes. Concurrent API readers therefore see either the previous complete artifact or the new complete artifact, never a partially written pickle; if serialization fails, the existing last-known-good artifact is preserved and the temporary file is removed.

**Risk level:** High reliability value, low inference/API risk (artifact format and model selection are unchanged). **Affected modules:** `app/services/ai/predictor.py`, `tests/unit/test_prediction_model_outputs.py`. **Migration:** none.

**Regression evidence:** Focused predictor/readiness/split tests passed (**8 passed**), Python compilation and whitespace validation passed, and the full local regression suite passed (**277 passed** in 108.32s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.45 IMPLEMENTED — Collapse concurrent AI prediction cache misses

Prediction cache misses now use a per-symbol/timeframe single-flight lock. The first caller performs the expensive feature/training/inference work and fills the cache; concurrent callers for the same key re-check the cache and reuse that result, while unrelated keys remain able to run in parallel. Forced retraining uses the same key lock so it cannot delete artifacts in the middle of an in-process prediction.

**Risk level:** High performance/reliability value, low output/API risk (only duplicate work is removed; prediction values and cache TTLs are unchanged). **Affected modules:** `app/services/ai/predictor.py`, `tests/unit/test_prediction_model_outputs.py`. **Migration:** none.

**Regression evidence:** Focused predictor/readiness/split tests passed (**9 passed**), Python compilation and whitespace validation passed, and the full local regression suite passed (**278 passed** in 108.98s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.46 IMPLEMENTED — Batch news-ingestion URL deduplication

The scheduled news importer now loads existing article URLs in bounded batches before inserting new rows, instead of querying once per feed item. It also records URLs as they are queued, so duplicate articles returned by overlapping provider feeds are inserted only once in the same run. This lowers database round trips during refreshes without changing the public news payload or provider behavior.

**Risk level:** Medium operational-performance value, low data/API risk (existing rows are still preserved and only duplicate inserts are removed). **Affected modules:** `app/tasks/data_tasks.py`, `tests/integration/test_news_ingestion.py`. **Migration:** none.

**Regression evidence:** Focused news-ingestion test passed (**1 passed**), Python compilation and whitespace validation passed, and the full local regression suite passed (**279 passed** in 105.85s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.47 IMPLEMENTED — Harden provider-controlled News rendering

The News page now escapes provider-controlled titles, summaries, sources, related symbols and economic-calendar values before inserting them into the DOM. Article links are accepted only when they resolve to HTTP(S), and external links use `noopener noreferrer`; numeric calendar comparisons now also tolerate provider values that arrive as numbers instead of strings. This removes a client-side injection path without changing the page’s visual information architecture.

**Risk level:** High security/UX value, low compatibility risk (valid article links and display values remain visible; unsafe schemes are intentionally omitted). **Affected modules:** `frontend/templates/dashboard/news.html`, `tests/unit/test_news_template_safety.py`. **Migration:** none.

**Regression evidence:** News safety and ingestion checks passed (**2 passed**), extracted browser JavaScript passed `node --check`, Python compilation and whitespace validation passed, and the full local regression suite passed (**280 passed** in 109.82s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.48 IMPLEMENTED — Throttle duplicate empty-state News fetches

When the News table is empty, the public endpoint now uses a short shared in-progress marker before starting its background provider fetch. Refresh bursts therefore start one worker instead of one worker per request; the marker expires after 60 seconds so provider failures still recover automatically, and marker cleanup remains failure-safe.

**Risk level:** Medium availability/performance value, low response/API risk (the existing empty response remains `fetching: true`; only duplicate background work is suppressed). **Affected modules:** `app/api/v1/news.py`, `tests/integration/test_news_fetch_throttle.py`. **Migration:** none.

**Regression evidence:** Empty-state throttle test passed (**1 passed**), Python compilation and whitespace validation passed, and the full local regression suite passed (**281 passed** in 106.09s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.49 IMPLEMENTED — Collapse concurrent market-data cache misses

Direct Delta and Binance OHLCV fetches now use per-symbol/timeframe single-flight locks with a second cache check after lock acquisition. Concurrent requests and collector work for the same uncached candle set therefore share one completed provider response, while unrelated symbols/timeframes remain parallel; Yahoo multi-symbol batches keep their existing coalesced path.

**Risk level:** High upstream-load/performance value, low data/API risk (cache TTLs, provider routing and returned candle values are unchanged). **Affected modules:** `app/services/data/fetcher.py`, `tests/unit/test_market_data_singleflight.py`. **Migration:** none.

**Regression evidence:** Focused market-data, data-quality and prediction-history checks passed (**28 passed**), Python compilation and whitespace validation passed, and the full local regression suite passed (**282 passed** in 101.77s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.50 IMPLEMENTED — Encrypt admin provider access and refresh tokens

APIConfig access and refresh token writes now use the same Fernet at-rest protection as API keys and secrets. Reads tolerate legacy plaintext rows so existing deployments remain usable, while admin create/update and connection-test flows use credential accessors instead of raw token columns. API responses continue exposing presence booleans only.

**Risk level:** High credential-security value, low compatibility/API risk (no column shape or response fields changed; legacy values remain readable). **Affected modules:** `app/models/api_config.py`, `app/api/v1/admin.py`, `tests/unit/test_api_config_credentials.py`. **Migration:** none; newly written tokens are encrypted, and legacy values are read compatibly until the next edit.

**Regression evidence:** Focused credential, validation and provider-health checks passed (**22 passed**), Python compilation and whitespace validation passed, and the full local regression suite passed (**284 passed** in 110.78s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.51 IMPLEMENTED — Collapse direct Yahoo misses and enforce OHLCV cache size

Direct Yahoo OHLCV requests now use the same per-symbol/timeframe single-flight lock as Delta and Binance, preventing concurrent chart or signal requests from issuing duplicate provider calls. Yahoo batch reads and Delta prewarm reads now pass the requested minimum row count to the cache, so a short earlier response cannot satisfy a later indicator that needs more history.

**Risk level:** High upstream-load/performance and data-quality value, low API risk (provider routing, cache TTLs and response shapes are unchanged). **Affected modules:** `app/services/data/fetcher.py`, `tests/unit/test_market_data_singleflight.py`. **Migration:** none.

**Regression evidence:** Focused market-data single-flight checks passed (**3 passed**), Python compilation and whitespace validation passed, and the full local regression suite passed (**286 passed** in 116.18s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.52 IMPLEMENTED — Harden Markets and Morning Briefing rendering

Markets and Morning Briefing now share a small UI safety layer for provider/database values. Headlines and event text are escaped, external article links accept only HTTP(S), asset links accept numeric database IDs only, and inline `onclick` navigation was replaced with normal links. Signal badges also fall back to a neutral label for unknown signal types instead of echoing arbitrary values into HTML.

**Risk level:** High trust/security value, low UX/API risk (normal links preserve navigation and all approved display values remain visible). **Affected modules:** `frontend/static/js/app.js`, `frontend/static/js/pages/markets.js`, `frontend/static/js/pages/briefing.js`, `tests/unit/test_market_briefing_template_safety.py`. **Migration:** none.

**Regression evidence:** Overview and News rendering safety checks passed (**4 passed**), all changed JavaScript files passed `node --check`, Python compilation and whitespace validation passed, and the full local regression suite passed (**289 passed** in 113.41s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.53 IMPLEMENTED — Harden shared notifications, ticker and command palette

The global notification dropdown and toast system now render server messages as text rather than HTML. Ticker symbols are escaped and live updates match DOM nodes through their dataset instead of interpolating a provider value into a CSS selector. The command palette now validates asset IDs and escapes asset names, so the shared navigation surface is safe across authenticated pages.

**Risk level:** High cross-page trust/security value, low UX/API risk (notification interactions and ticker updates retain their existing behavior). **Affected modules:** `frontend/static/js/app.js`, `frontend/templates/partials/base.html`, `tests/unit/test_global_ui_safety.py`. **Migration:** none.

**Regression evidence:** Global UI safety checks passed (**6 passed**), `app.js` passed `node --check`, Python compilation and whitespace validation passed, and the full local regression suite passed (**291 passed** in 115.49s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.54 IMPLEMENTED — Harden Dashboard live rendering and navigation

Dashboard opportunities, signals, heatmap cells and Decision Inspector context now escape live values before HTML insertion. Asset and market navigation use validated links, while signal rows preserve click behavior through safe dataset-driven handlers with keyboard support. This prevents provider or persisted reasoning text from becoming executable markup in the primary dashboard.

**Risk level:** High trust/security and accessibility value, low UX/API risk (navigation behavior is preserved and keyboard access is improved). **Affected modules:** `frontend/static/js/app.js`, `frontend/static/js/pages/dashboard.js`, `tests/unit/test_dashboard_template_safety.py`. **Migration:** none.

**Regression evidence:** Dashboard, global widget and overview rendering checks passed (**7 passed**), Dashboard and core JavaScript files passed `node --check`, Python compilation and whitespace validation passed, and the full local regression suite passed (**293 passed** in 111.91s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.55 IMPLEMENTED — Harden admin Assets rendering and controls

Admin Assets now escapes symbols, names, exchange/source values and catalog labels. Asset status, removal, selection, Delta catalog toggles and search-result additions use dataset-backed event listeners instead of embedding provider strings in inline handlers. Existing super-admin/view-only permissions, bulk operations and asset filtering remain unchanged.

**Risk level:** High admin-session security value, low behavior/API risk (the same handlers and payloads are used through safer bindings). **Affected modules:** `frontend/templates/admin/assets.html`, `tests/unit/test_admin_assets_template_safety.py`. **Migration:** none.

**Regression evidence:** Admin Assets, Dashboard and shared widget safety checks passed (**6 passed**), shared JavaScript passed `node --check`, Python compilation and whitespace validation passed, and the full local regression suite passed (**295 passed** in 120.60s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.56 IMPLEMENTED — Harden admin User Management rendering

Admin User Management now escapes usernames, emails, roles, plans and approval values before rendering. User action buttons carry only validated IDs and dataset values, so delete/edit/toggle/trial actions no longer embed a database username inside inline JavaScript; existing super-admin/view-only permissions and API calls remain unchanged.

**Risk level:** High admin-session security value, low behavior/API risk (actions retain their existing targets and confirmation flows). **Affected modules:** `frontend/templates/admin/users.html`, `tests/unit/test_admin_users_template_safety.py`. **Migration:** none.

**Regression evidence:** Admin Users, Assets, Dashboard and shared widget safety checks passed (**4 passed**), shared JavaScript passed `node --check`, Python compilation and whitespace validation passed, and the full local regression suite passed (**297 passed** in 111.44s). Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.57 IMPLEMENTED — Collapse concurrent economic-calendar refreshes

The public economic-calendar route now uses a process-local single-flight lock around its request-time provider fallback. Waiting requests re-check the shared cache and database after the first refresh completes, so the three overview surfaces that load the calendar together no longer duplicate Forex Factory requests or the batch upsert work. The existing timezone parsing, one-hour cache and response shape are unchanged.

**Risk level:** Medium upstream-load/performance value, low API/data risk (only concurrent cold-cache coordination changed). **Affected modules:** `app/api/v1/news.py`, `tests/integration/test_economic_calendar_fetch_throttle.py`. **Migration:** none.

**Regression evidence:** Economic-calendar and News throttle checks passed (**2 passed**), JavaScript syntax and whitespace validation passed. The full local regression suite is still pending for this checkpoint.

### 7.58 IMPLEMENTED — Collapse concurrent heatmap rebuilds

The heatmap endpoint now serializes only its cold rebuild and re-checks the shared cache after waiting. This prevents simultaneous dashboard loads after a restart or failed prewarm from repeating the active-universe query and market-data fallback, while warm requests remain immediate and the payload remains unchanged.

**Risk level:** Medium upstream-load/performance value, low API/data risk (cache-hit behavior and tile values are unchanged). **Affected modules:** `app/api/v1/market_data.py`, `tests/unit/test_heatmap_singleflight.py`. **Migration:** none.

**Regression evidence:** Heatmap single-flight test passed (**1 passed**), Python compilation and whitespace validation passed. The full local regression suite is still pending for this checkpoint.

### 7.59 IMPLEMENTED — Optimize and harden admin log surfaces

Admin User Management, Sessions and Audit Log queries now eager-load their related users, removing the per-row lazy-load pattern that grew linearly with page size. System Logs now exposes its page count so the existing pager can work; both log screens escape database values before HTML insertion, and Audit Log actions use event listeners with the pager visibility bug removed.

**Risk level:** High admin performance/trust value, low API/UI compatibility risk (the System Logs response is additive and existing controls retain their behavior). **Affected modules:** `app/api/v1/admin.py`, `frontend/templates/admin/logs.html`, `frontend/templates/admin/audit_log.html`, `tests/unit/test_admin_logs_audit_template_safety.py`. **Migration:** none.

**Regression evidence:** Admin log/audit template checks, audit-log, and session tracking checks passed (**13 passed**), Python compilation, inline-admin JavaScript parsing and whitespace validation passed. The full local regression suite is still pending for this checkpoint.

### 7.60 IMPLEMENTED — Harden admin Login Sessions rendering

Login Sessions now escapes usernames, addresses, device labels and timestamps before rendering. Revoke and selection actions carry validated numeric IDs through data attributes instead of embedding account names in inline JavaScript; refresh, filtering, selection and paging use event listeners. The pager is now able to become visible because its blocking `!important` inline style was removed.

**Risk level:** High admin trust/security and accessibility value, low behavior/API risk (permission checks and session endpoints are unchanged). **Affected modules:** `frontend/templates/admin/sessions.html`, `tests/unit/test_admin_sessions_template_safety.py`. **Migration:** none.

**Regression evidence:** Sessions template checks passed (**2 passed**), inline JavaScript parsing and whitespace validation passed. The full local regression suite is still pending for this checkpoint.

### 7.61 IMPLEMENTED — Harden admin Telegram Alerts rendering

Telegram Alerts now escapes channel names, chat IDs, market labels and configured timeframes before rendering. Channel IDs are validated before API paths are built, channel actions use dataset-backed listeners instead of embedding names in inline JavaScript, and the Add/Save/Test/Send controls use event bindings while preserving the existing permission behavior and API payloads.

**Risk level:** High admin trust/security value, low workflow/API risk (approved Telegram configuration values and existing actions remain available). **Affected modules:** `frontend/templates/admin/telegram_alerts.html`, `tests/unit/test_admin_telegram_template_safety.py`. **Migration:** none.

**Regression evidence:** Telegram Alerts safety checks and Telegram channel/delivery integration checks passed (**10 passed**), inline JavaScript parsing and whitespace validation passed. The full local regression suite is still pending for this checkpoint.

### 7.62 IMPLEMENTED — Harden admin API Configurations rendering

API Configurations now escapes provider metadata, numeric status details and connection-test responses before HTML insertion. Configuration IDs and supported actions are validated before API paths are built, while tabs, modal controls and dynamic config actions use event listeners instead of inline handlers; secret credential values remain input-only and are never rendered in rows or logs.

**Risk level:** High admin trust/security value, low workflow/API risk (provider management, tests, logs and credential entry retain their existing behavior). **Affected modules:** `frontend/templates/admin/api_configs.html`, `tests/unit/test_admin_api_configs_template_safety.py`. **Migration:** none.

**Regression evidence:** API Configurations safety, provider-health and credential checks passed (**10 passed**), inline JavaScript parsing and whitespace validation passed. The full local regression suite is still pending for this checkpoint.

### 7.63 IMPLEMENTED — Harden Platform Configuration and Security controls

Platform Configuration now escapes page labels, routes and timeframe tokens before HTML insertion, replaces inline page/timeframe/gate controls with event listeners, validates reorder/remove indexes, and treats API error payloads as failures. Security now binds actions without inline handlers, enforces the server's 5-minute to 30-day timeout contract in the browser, validates numeric Telegram security chat IDs, and suppresses duplicate save/test requests while one is in flight.

**Risk level:** High admin trust/security and operational-safety value, low API/UI compatibility risk (existing endpoints, permissions and settings payloads are preserved). **Affected modules:** `frontend/templates/admin/platform_config.html`, `frontend/templates/admin/security.html`, `tests/unit/test_admin_platform_config_template_safety.py`, `tests/unit/test_admin_security_template_safety.py`. **Migration:** none.

**Regression evidence:** Platform Configuration, Security, API Configuration and Telegram Alerts checks passed (**9 passed**), both updated inline JavaScript blocks parsed successfully, whitespace validation passed, and the full local regression suite passed (**312 passed** in 122.22s).

### 7.64 IMPLEMENTED - Harden Admin Dashboard rendering

Admin Dashboard rendering now validates and escapes server-provided dashboard values, uses bounded numeric display helpers, and binds actions through validated event listeners instead of inline handlers. This reduces the chance that operational metrics or action labels can break the page or become executable markup.

**Risk level:** High admin safety and trust value, low endpoint compatibility risk. **Affected modules:** `frontend/templates/admin/index.html`, `tests/unit/test_admin_dashboard_template_safety.py`. **Migration:** none.

**Regression evidence:** Admin Dashboard safety checks, inline JavaScript parsing and whitespace validation passed; the full local suite remains green after subsequent slices.

### 7.65 IMPLEMENTED - Scope summary caches to the full asset universe

Market summary caches now include the full-universe scope in their cache identity and the summary route avoids reusing a partial request result for a full dashboard request. This prevents incomplete aggregate metrics from being shown after a narrower request warms the cache.

**Risk level:** High correctness value for aggregate metrics, low response-shape risk. **Affected modules:** `app/api/v1/market_data.py`, `tests/integration/test_summary_cache_scope.py`. **Migration:** none.

**Regression evidence:** Summary-cache scope and summary single-flight checks passed; the full local suite remains green after subsequent slices.

### 7.66 IMPLEMENTED - Serialize indicator summary cold builds

Indicator summary cache misses now use single-flight construction with a double-checked cache read. Concurrent dashboard requests therefore share one expensive indicator build instead of multiplying provider and calculation work.

**Risk level:** High performance value, low API compatibility risk. **Affected modules:** `app/api/v1/market_data.py`, `tests/unit/test_summary_singleflight.py`. **Migration:** none.

**Regression evidence:** Indicator summary concurrency checks passed, including concurrent cold-request coverage; the full local suite remains green after subsequent slices.

### 7.67 IMPLEMENTED - Serialize AI summary cold builds

AI summary cache misses now use a dedicated single-flight path, preserving the existing cache contract while preventing duplicate model and summary work during simultaneous page loads.

**Risk level:** High compute-cost reduction, low behavior risk because only concurrent cache misses are serialized. **Affected modules:** `app/api/v1/market_data.py`, `tests/unit/test_summary_singleflight.py`. **Migration:** none.

**Regression evidence:** AI summary concurrency checks passed with the indicator summary coverage; the full local suite remains green after subsequent slices.

### 7.68 IMPLEMENTED - Complete Admin User Management controls

Admin User Management now validates account identifiers and action payloads in the browser, escapes account and status data, handles API failures consistently, and uses event-bound controls for account actions. This removes unsafe username-bearing inline handlers and makes failure states visible instead of silently treating error payloads as success.

**Risk level:** High administrative access-control value, low endpoint compatibility risk. **Affected modules:** `frontend/templates/admin/users.html`, `tests/unit/test_admin_users_template_safety.py`. **Migration:** none.

**Regression evidence:** User Management safety checks and script parsing passed; the full local suite remains green after subsequent slices.

### 7.69 IMPLEMENTED - Harden shared toast and account banners

Shared toast, notification, ticker, trial and account-banner rendering now escapes text, validates identifiers and URLs, clamps numeric display values, and treats API error payloads as failures. This protects every page that uses the shared UI layer and avoids duplicate or misleading account-state actions.

**Risk level:** High cross-page trust value, moderate UI compatibility risk because shared helpers affect many screens. **Affected modules:** `frontend/static/js/app.js`, `tests/unit/test_global_ui_safety.py`. **Migration:** none.

**Regression evidence:** Global UI safety checks and JavaScript syntax validation passed; the full local suite remains green after subsequent slices.

### 7.70 IMPLEMENTED - Harden Scanner rendering and actions

The Scanner page now renders provider and scan values through shared escaping helpers, validates preset filters, prevents duplicate scans, handles failed responses, safely quotes CSV cells including spreadsheet-formula prefixes, and revokes generated object URLs. This improves both operator trust and repeated-use performance.

**Risk level:** High UI safety and reliability value, low API compatibility risk. **Affected modules:** `frontend/static/js/pages/scanner.js`, `tests/unit/test_scanner_template_safety.py`. **Migration:** none.

**Regression evidence:** Scanner safety checks passed, JavaScript syntax validation passed, and the full local suite passed after the Scanner slice.

### 7.71 IMPLEMENTED - Harden Delta Scanner flows

Delta Scanner MTF, screener, indicator and symbol-picker flows now validate response shapes and inputs, escape dynamic values, encode asset links, recognize API error payloads, and suppress duplicate refresh, apply and scan requests. This protects the most data-dense scanner surface without changing its endpoint contract.

**Risk level:** High operational-data trust value, moderate UI compatibility risk due to broad dynamic rendering changes. **Affected modules:** `frontend/static/js/pages/delta_scanner.js`, `tests/unit/test_delta_scanner_safety.py`, `tests/unit/test_scanner_template_safety.py`. **Migration:** none.

**Regression evidence:** Delta Scanner and shared Scanner safety checks passed, and JavaScript syntax validation passed.

### 7.72 IMPLEMENTED - Harden Delta Bubbles rendering

Delta Bubbles now accepts only canonical group values, validates response arrays and numerics, escapes ticker and metric labels, encodes query parameters, and prevents duplicate group loads. This avoids malformed dashboard states and unnecessary provider work from repeated refreshes.

**Risk level:** High UI safety and performance value, low API compatibility risk. **Affected modules:** `frontend/static/js/pages/delta_bubbles.js`, `tests/unit/test_delta_bubbles_safety.py`. **Migration:** none.

**Regression evidence:** Delta Bubbles safety checks and JavaScript syntax validation passed.

### 7.73 IMPLEMENTED - Harden Asset Detail interactions

Asset Detail controls now use dataset-backed event listeners, validate asset and timeframe values, escape dynamic provider, DCA, sentiment and AI content, guard duplicate AI requests, and enforce safe links and numeric rendering. This removes inline handlers from a high-value trading workflow and makes unavailable analysis explicit.

**Risk level:** High trading-workflow trust value, moderate UI compatibility risk because multiple detail panels share the control wiring. **Affected modules:** `frontend/templates/asset/detail.html`, `tests/unit/test_asset_detail_safety.py`. **Migration:** none.

**Regression evidence:** Asset Detail safety checks, inline script parsing and whitespace validation passed; the full local suite passed after the Asset Detail slice.

### 7.74 IMPLEMENTED - Harden scanner API caches and request boundaries

Delta scanner API cache misses now use scoped single-flight locks with double-checked reads for MTF, bubbles, screener universes and indicator universes. MTF status results use bounded, deduplicated symbol lists and short-lived hashed cache keys. Scanner request bodies and condition payloads now enforce object/list/string bounds, supported markets and timeframes, valid combinators, and safe condition shapes before worker execution.

**Risk level:** High performance and operational-safety value, low response-shape compatibility risk. **Affected modules:** `app/api/v1/scanner.py`, `app/services/scanner/delta_market_screener.py`, `app/services/scanner/delta_indicator_scanner.py`, `tests/unit/test_scanner_backend_hardening.py`. **Migration:** none.

**Regression evidence:** Scanner backend focused checks passed (**4 passed**), Python compilation and whitespace validation passed, and the full local regression suite passed (**335 passed** in 131.81s).

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

**Session 8 (Phase 1 — signal reproducibility provenance, §7.29):**
- `app/services/signals/provenance.py` — shared, persistence-boundary metadata builder using the existing OHLCV fingerprint implementation.
- `app/services/ai/predictor.py` — explicit calibrated-ensemble version only on real model results; neutral fallbacks carry no model version.
- `app/models/signal.py`, `app/api/v1/signals.py`, `app/tasks/signal_tasks.py`, `app/__init__.py` — persist and serialize source, engine/model version, candle count, bounds and data fingerprint across both live writers.
- `frontend/static/js/pages/dashboard.js` — show provenance context in the Decision Inspector and avoid implying every signal was selected by AI.
- `migrations/versions/9b3c4d5e6f7a_add_signal_reproducibility_metadata.py` — additive nullable signal provenance migration.
- `tests/unit/test_signal_provenance.py`, `tests/unit/test_signal_quality_contract.py` — provenance and serialization regression coverage.

**Session 9 (Phase 2 — automatic confidence honesty, §7.30):**
- `app/services/signals/engine.py` — remove the hardcoded automatic AI confidence component while preserving the legacy field at zero.
- `frontend/templates/dashboard/signals.html` — remove the duplicate fabricated AI score bar.
- `tests/unit/test_signal_engine_confidence.py` — verify automatic scores exclude the placeholder and real manual AI input remains separate.

**Session 10 (Phase 2 — prediction model-version provenance, §7.31):**
- `app/models/prediction.py` — persist and serialize the calibrated AI model version; tolerate transient rows without a database-assigned timestamp during serialization.
- `app/services/ai/prediction_records.py` — shared canonical mapper for all AI prediction writers.
- `app/api/v1/predictions.py`, `app/api/v1/market_data.py`, `app/tasks/data_tasks.py` — carry model versions through direct, batch, and scheduled paths; do not persist neutral fallbacks; version the AI summary cache key.
- `app/__init__.py`, `migrations/versions/ac4d5e6f7a8b_add_prediction_model_version.py` — additive SQLite fallback and Alembic migration.
- `frontend/templates/dashboard/ai_insights.html` — show model/version provenance and probability caveat with escaped metadata.
- `tests/unit/test_prediction_model_version.py` — model mapping and legacy serialization regression coverage.

**Session 11 (Phase 2/3 — AI input data-quality context, §7.32):**
- `app/models/prediction.py`, `app/services/ai/prediction_records.py` — persist and map the existing data-quality snapshot on AI predictions.
- `app/api/v1/predictions.py`, `app/api/v1/market_data.py`, `app/tasks/data_tasks.py` — assess and return quality context through direct, batch, and scheduled paths; rotate the summary cache key to `v3`.
- `app/__init__.py`, `migrations/versions/bd5e6f7a8b9c_add_prediction_data_quality.py` — additive SQLite fallback and Alembic migration.
- `frontend/templates/dashboard/ai_insights.html` — render input-quality status, candle age, and actionable quality issues without adjusting model confidence.
- `tests/unit/test_prediction_model_version.py`, `tests/unit/test_data_quality.py` — persistence/serialization and quality-contract regression coverage.

**Session 12 (Phase 2 — truthful ensemble member outputs, §7.33):**
- `app/services/ai/predictor.py` — retain actual per-member bullish probabilities through training and inference-only cache paths; label partial/heuristic results honestly.
- `app/models/prediction.py`, `app/services/ai/prediction_records.py` — persist and map member outputs without changing the ensemble mean.
- `app/api/v1/predictions.py`, `app/api/v1/market_data.py`, `app/tasks/data_tasks.py` — carry member outputs through direct, batch, and scheduled responses; rotate the summary cache key to `v4`.
- `app/__init__.py`, `migrations/versions/c6f7a8b9c0d1_add_prediction_model_outputs.py` — additive SQLite fallback and Alembic migration.
- `frontend/templates/dashboard/ai_insights.html` — show actual member values and percentage-point spread, with a heuristic fallback warning.
- `tests/unit/test_prediction_model_outputs.py`, `tests/unit/test_prediction_model_version.py` — inference/cache and persistence/serialization regression coverage.

**Session 13 (Phase 5 — Decision Inspector historical context, §7.34):**
- `app/api/v1/signals.py` — one grouped asset/timeframe history query for active signal list/detail responses.
- `frontend/static/js/pages/dashboard.js` — show decisive accuracy, sample composition and average P&L with explicit non-forecast wording.
- `tests/integration/test_signal_history_context.py` — mixed-outcome and empty-history response coverage.

**Session 14 (Phase 4 — explicit no-signal state, §7.35):**
- `app/services/signals/engine.py` — add `SIGNAL`/`NO_SIGNAL`/`UNAVAILABLE` analysis states and stable no-signal reasons.
- `app/api/v1/signals.py` — preserve reason metadata for position-analysis and market-board unavailable responses.
- `frontend/templates/markets/terminal.html`, `frontend/templates/asset/detail.html` — render concrete no-signal explanations.
- `tests/unit/test_signal_analysis_state.py` — cover HOLD, below-threshold and unavailable analysis states.

**Session 15 (performance/correctness — prediction freshness, §7.36):**
- `app/api/v1/predictions.py`, `app/api/v1/market_data.py`, `app/tasks/data_tasks.py` — select the newest recent prediction consistently and invalidate per-asset/timeframe history context after evaluation.
- `tests/integration/test_prediction_history_route.py`, `tests/unit/test_prediction_cache_freshness.py` — cover newest-row selection and post-evaluation cache freshness.

**Session 16 (accountability/performance — model-performance coverage, §7.37):**
- `app/api/v1/predictions.py` — add SQL-aggregated versioned/legacy coverage and model-version accuracy without loading prediction rows into Python.
- `frontend/templates/dashboard/model_performance.html` — show evaluation scope and version accuracy, preserve the chart canvas across empty-state refreshes, clamp numeric bars and escape database-backed labels.
- `tests/integration/test_model_performance_route.py` — verify versioned coverage, legacy grouping and the additive empty response contract.

**Session 17 (operations/security — provider verification freshness, §7.38):**
- `app/services/provider_health.py`, `app/models/api_config.py` — expose a side-effect-free health state based on the last successful connection test and safe timestamp handling.
- `app/api/v1/admin.py` — remove duplicate API-config serialization for flat/grouped responses.
- `frontend/templates/admin/api_configs.html` — show verification state and attention counts, remove name-bearing inline arguments and escape admin-rendered provider/test-log data.
- `tests/unit/test_provider_health.py` — cover all health states, stale thresholds, aware timestamps and model serialization.

**Session 18 (ML/performance — predictor readiness, §7.39):**
- `app/services/ai/predictor.py` — make the API readiness check use the same all-installed-members contract as inference-only prediction.
- `tests/unit/test_predictor_readiness.py` — prevent partial model files from being reported as request-safe.

**Session 19 (ML integrity — purged calibration folds, §7.40):**
- `app/services/ai/predictor.py` — purge the triple-barrier label horizon before each chronological validation fold.
- `tests/unit/test_predictor_splits.py` — verify temporal ordering, purge distance and last-row protection.

**Session 20 (ML deployment integrity — versioned artifacts, §7.41):**
- `app/services/ai/predictor.py` — bump the calibrated contract to v2 and include it in model artifact keys.
- `tests/unit/test_prediction_model_outputs.py` — verify output provenance and artifact-key invalidation when the contract changes.

**Session 21 (P0 boundary hardening — API configuration validation, §7.42):**
- `app/services/api_config_validation.py` — centralize create/update normalization and validation for provider configuration payloads.
- `app/api/v1/admin.py` — apply the shared validator before configuration writes.
- `tests/unit/test_api_config_validation.py` — cover valid normalization, malformed bodies, incompatible providers, partial updates and ambiguous values.

**Session 22 (AI accountability — outcome composition, §7.43):**
- `app/api/v1/predictions.py` — aggregate evaluated bullish/bearish/neutral/unknown outcomes and decisive directional accuracy in SQL.
- `frontend/templates/dashboard/model_performance.html` — show neutral sample count and decisive accuracy alongside the existing coverage caveat.
- `tests/integration/test_model_performance_route.py` — verify outcome composition, decisive accuracy and the empty response contract.

**Session 23 (ML reliability — atomic model artifact publication):**
- `app/services/ai/predictor.py` — serialize models to a same-directory temporary file and publish with `os.replace`, preserving the last good artifact when serialization fails.
- `tests/unit/test_prediction_model_outputs.py` — verify completed-file publication, target replacement and temporary-file cleanup on failure.

**Session 24 (ML performance — prediction single-flight):**
- `app/services/ai/predictor.py` — add per-key locks around cache-miss computation and forced retraining, with a second cache check for waiting callers.
- `tests/unit/test_prediction_model_outputs.py` — verify concurrent identical misses invoke the expensive ensemble computation once and share the cached result.

**Session 25 (data-ingestion performance — batched news deduplication):**
- `app/tasks/data_tasks.py` — replace per-article URL existence queries with bounded batch lookups and same-run duplicate guards.
- `tests/integration/test_news_ingestion.py` — verify existing, duplicate, missing-URL and new feed-item behavior.

**Session 26 (UI security — provider-controlled News rendering):**
- `frontend/templates/dashboard/news.html` — escape provider values, allow only HTTP(S) article links, add safe external-link attributes, and normalize numeric calendar comparisons.
- `tests/unit/test_news_template_safety.py` — lock the rendering safety contract against raw provider interpolation.

**Session 27 (News reliability — empty-state fetch throttle):**
- `app/api/v1/news.py` — add a short shared in-progress marker so empty-state refresh bursts do not spawn duplicate provider jobs.
- `tests/integration/test_news_fetch_throttle.py` — verify repeated empty-state requests start only one background fetch.

**Session 28 (market-data performance — OHLCV single-flight):**
- `app/services/data/fetcher.py` — add per-key miss locks and double-checked cache reads for direct Delta and Binance candle fetches.
- `tests/unit/test_market_data_singleflight.py` — verify concurrent identical Delta misses issue one provider request and share the cached frame.

**Session 29 (credential security — encrypted admin provider tokens):**
- `app/models/api_config.py` — add encrypted setters/getters for access and refresh tokens with legacy plaintext-read compatibility.
- `app/api/v1/admin.py` — route admin create/update/connection-test token flows through the accessors.
- `tests/unit/test_api_config_credentials.py` — verify encrypted storage and legacy plaintext reads.

**Session 30 (market-data performance — Yahoo single-flight and cache-size guard):**
- `app/services/data/fetcher.py` — collapse direct Yahoo cache misses and require the requested minimum row count in batch/prewarm cache reads.
- `tests/unit/test_market_data_singleflight.py` — verify concurrent Yahoo calls share one provider request and short cached frames are refetched for larger limits.

**Session 31 (UI security — shared overview rendering safety):**
- `frontend/static/js/app.js` — add shared HTML, URL, asset-ID and DOM-ID safety helpers; neutralize unknown signal badge labels.
- `frontend/static/js/pages/markets.js` — escape live signal, opportunity, heatmap, news and event values; use safe links instead of inline navigation.
- `frontend/static/js/pages/briefing.js` — escape movers, levels, headlines, economic events and insight text; validate asset IDs and article URLs.
- `tests/unit/test_market_briefing_template_safety.py` — protect the overview rendering contract.

**Session 32 (UI security — global widget rendering safety):**
- `frontend/static/js/app.js` — render toast/notification text safely, protect ticker symbol rendering and selector matching, and sanitize market registry options.
- `frontend/templates/partials/base.html` — escape and validate lazy-loaded command-palette asset entries.
- `tests/unit/test_global_ui_safety.py` — protect shared widget and navigation rendering contracts.

**Session 33 (UI security/accessibility — Dashboard rendering safety):**
- `frontend/static/js/pages/dashboard.js` — escape opportunity, signal, inspector and heatmap values; replace inline navigation with validated links and keyboard-capable row handlers.
- `tests/unit/test_dashboard_template_safety.py` — protect the Dashboard rendering and navigation contract.

**Session 34 (UI security — admin Assets rendering safety):**
- `frontend/templates/admin/assets.html` — escape provider/catalog values and replace inline asset/catalog/search handlers with dataset-backed event listeners.
- `tests/unit/test_admin_assets_template_safety.py` — protect the admin Assets rendering and control-binding contract.

**Session 35 (UI security — admin User Management rendering safety):**
- `frontend/templates/admin/users.html` — escape account values and replace username-bearing inline actions with dataset-backed event listeners.
- `tests/unit/test_admin_users_template_safety.py` — protect the admin User Management rendering and control-binding contract.

**Session 36 (backend reliability — economic-calendar cold-cache single-flight, §7.57):**
- `app/api/v1/news.py` — serialize concurrent request-time Forex Factory refreshes and double-check the shared cache/database before fetching, while retaining the existing batch upsert and response contract.
- `tests/integration/test_economic_calendar_fetch_throttle.py` — verify simultaneous cold requests share one provider refresh.

**Session 37 (backend reliability — heatmap cold-cache single-flight, §7.58):**
- `app/api/v1/market_data.py` — serialize the expensive cold heatmap rebuild and double-check the shared cache before building the active-universe payload.
- `tests/unit/test_heatmap_singleflight.py` — verify simultaneous cold requests share one heatmap build.

**Session 38 (admin performance/UI safety — log and audit operations, §7.59):**
- `app/api/v1/admin.py` — eager-load related users for User Management, Sessions and Audit Log responses to remove per-row relationship queries; expose System Logs page count metadata.
- `frontend/templates/admin/logs.html` — escape system-log values and activate the existing pagination surface with event-bound controls.
- `frontend/templates/admin/audit_log.html` — escape audit values, replace inline controls with event listeners, and fix the pager visibility style.
- `tests/unit/test_admin_logs_audit_template_safety.py` — protect the admin log/audit rendering and control-binding contracts.

**Session 39 (UI security/accessibility — admin Login Sessions rendering safety, §7.60):**
- `frontend/templates/admin/sessions.html` — escape session/account values, replace username-bearing inline revoke actions with dataset-backed event listeners, and fix all filter/pager controls to use event bindings.
- `tests/unit/test_admin_sessions_template_safety.py` — protect the Login Sessions rendering and control-binding contract.

**Session 40 (UI security/accessibility — Telegram Alerts rendering safety, §7.61):**
- `frontend/templates/admin/telegram_alerts.html` — escape channel/config values, validate channel IDs, replace channel-name-bearing inline actions with dataset-backed event listeners, and bind admin controls without inline handlers.
- `tests/unit/test_admin_telegram_template_safety.py` — protect the Telegram Alerts rendering and control-binding contract.

**Session 41 (UI security/accessibility — API Configurations rendering safety, §7.62):**
- `frontend/templates/admin/api_configs.html` — escape provider/test-result metadata, validate configuration IDs and actions, replace inline tab/modal/config handlers with event bindings, and keep credential values out of rendered markup.
- `tests/unit/test_admin_api_configs_template_safety.py` — protect the API Configurations rendering and control-binding contract.

**Session 42 (UI security/accessibility — Platform Configuration and Security controls, §7.63):**
- `frontend/templates/admin/platform_config.html` — escape configurable page/timeframe values, replace inline controls with event listeners, validate timeframe mutations, and handle API error responses consistently.
- `frontend/templates/admin/security.html` — replace inline actions, validate timeout/chat inputs, and suppress duplicate save/test requests.
- `tests/unit/test_admin_platform_config_template_safety.py`, `tests/unit/test_admin_security_template_safety.py` — protect both admin control surfaces.

**Session 43 (UI security - Admin Dashboard rendering, §7.64):**
- `frontend/templates/admin/index.html` - validate and escape dashboard values, bound numeric displays, and bind actions without inline handlers.
- `tests/unit/test_admin_dashboard_template_safety.py` - protect the Admin Dashboard rendering contract.

**Session 44 (backend correctness - full-universe summary cache scope, §7.65):**
- `app/api/v1/market_data.py` - keep partial and full-universe summary cache entries distinct.
- `tests/integration/test_summary_cache_scope.py` - verify full-universe requests do not reuse partial summaries.

**Session 45 (backend performance - indicator summary single-flight, §7.66):**
- `app/api/v1/market_data.py` - serialize concurrent indicator summary cold builds with double-checked cache reads.
- `tests/unit/test_summary_singleflight.py` - verify concurrent indicator summary misses share one build.

**Session 46 (backend performance - AI summary single-flight, §7.67):**
- `app/api/v1/market_data.py` - serialize concurrent AI summary cold builds while preserving cache semantics.
- `tests/unit/test_summary_singleflight.py` - verify concurrent AI summary misses share one build.

**Session 47 (UI security/accessibility - complete Admin User Management controls, §7.68):**
- `frontend/templates/admin/users.html` - validate account actions, escape values and replace inline controls with event listeners.
- `tests/unit/test_admin_users_template_safety.py` - protect the User Management control contract.

**Session 48 (UI security - shared toast and account banners, §7.69):**
- `frontend/static/js/app.js` - harden shared toast, notification, ticker, trial and account-banner rendering and error handling.
- `tests/unit/test_global_ui_safety.py` - protect shared UI helpers.

**Session 49 (UI security/performance - Scanner rendering and actions, §7.70):**
- `frontend/static/js/pages/scanner.js` - escape dynamic scan data, validate presets, prevent duplicate scans, and safely export CSV.
- `tests/unit/test_scanner_template_safety.py` - protect Scanner rendering and action safety.

**Session 50 (UI security/performance - Delta Scanner flows, §7.71):**
- `frontend/static/js/pages/delta_scanner.js` - validate and escape MTF, screener, indicator and symbol-picker data, and suppress duplicate requests.
- `tests/unit/test_delta_scanner_safety.py`, `tests/unit/test_scanner_template_safety.py` - protect Delta Scanner flows.

**Session 51 (UI security/performance - Delta Bubbles rendering, §7.72):**
- `frontend/static/js/pages/delta_bubbles.js` - enforce canonical groups, safe rendering and duplicate-load protection.
- `tests/unit/test_delta_bubbles_safety.py` - protect Delta Bubbles rendering.

**Session 52 (UI security/accessibility - Asset Detail interactions, §7.73):**
- `frontend/templates/asset/detail.html` - replace inline controls, validate identifiers/timeframes, escape dynamic panel data and guard duplicate AI requests.
- `tests/unit/test_asset_detail_safety.py` - protect Asset Detail rendering and control wiring.

**Session 53 (backend performance/safety - scanner API caches and request boundaries, §7.74):**
- `app/api/v1/scanner.py` - add scoped single-flight cache builds, bounded status inputs and request validation.
- `app/services/scanner/delta_market_screener.py`, `app/services/scanner/delta_indicator_scanner.py` - reject malformed condition items before field access.
- `tests/unit/test_scanner_backend_hardening.py` - verify concurrent cache-build coalescing and invalid request rejection.

### 7.75 IMPLEMENTED - Harden portfolio input boundaries

Portfolio position creation and updates now validate symbol types and syntax before querying the asset catalog, enforce finite positive quantity/price bounds, and reject non-string or overlong notes instead of relying on database behavior. The limits match the existing `PortfolioItem` schema and prevent malformed JSON from raising attribute errors or allowing unbounded financial values into the portfolio workflow.

**Risk level:** High input-integrity and operational-safety value, low compatibility risk (valid symbols and values remain accepted; malformed or out-of-contract values receive `400`). **Affected modules:** `app/api/v1/portfolio.py`, `tests/unit/test_portfolio_input_validation.py`. **Migration:** none.

**Regression evidence:** Portfolio input, risk and template checks passed (**20 passed**), Python compilation and whitespace validation passed. Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

### 7.76 IMPLEMENTED - Harden portfolio position workflow and rendering

Portfolio rendering now escapes asset data and validates IDs/numbers before DOM insertion. Position actions are delegated through event listeners, duplicate add/stop/delete requests are suppressed, failures are shown instead of reported as success, stop losses can be edited after entry, and a completed refresh correctly replaces stale rows with the empty state. Mixed-currency headline totals are grouped rather than blended as raw rupee and dollar values.

**Risk level:** High trust, risk-management UX and data-display value, low API compatibility risk (existing endpoints and payloads are preserved). **Affected modules:** `frontend/templates/dashboard/portfolio.html`, `tests/unit/test_portfolio_template_safety.py`. **Migration:** none.

**Regression evidence:** Portfolio template/input/risk checks passed (**20 passed**), extracted browser JavaScript passed `node --check`, and whitespace validation passed. Production deployment verification is pending because the security reviewer requires explicit authorization for source transfer to `ubuntu@140.238.247.245`; the safe production plan is source/health checks plus isolated tests only, not the mutating integration suite.

**Session 54 (backend safety/performance - portfolio input boundaries, §7.75):**
- `app/api/v1/portfolio.py` - validate symbols, finite bounded financial values and the persisted notes length before ORM writes.
- `tests/unit/test_portfolio_input_validation.py` - cover malformed types, bounds, symbol normalization and schema-aligned notes.

**Session 55 (UI safety/risk workflow - portfolio position controls, §7.76):**
- `frontend/templates/dashboard/portfolio.html` - escape holdings, validate IDs/numbers, coalesce reads, guard mutations, support post-entry stop-loss editing and clear stale rows.
- `tests/unit/test_portfolio_template_safety.py` - protect portfolio event wiring, numeric limits, rendering and empty-state refresh behavior.

**Session 56 (backend safety/performance - Watchlist API boundaries, §7.77):**
- `app/api/v1/watchlist.py` - validate list/item payloads, enforce bounded alert prices and strict booleans, and invalidate per-user context cache after mutations.
- `tests/unit/test_watchlist_input_validation.py`, `tests/integration/test_watchlist_routes_validation.py` - cover helper and authenticated HTTP request-shape rejection.

**Session 57 (UI safety/performance - Watchlist workflow, §7.78):**
- `frontend/templates/dashboard/watchlist.html` - replace inline actions with delegated listeners, escape live context, coalesce list/context loads, suppress duplicate mutations and show API failures.
- `tests/unit/test_watchlist_template_safety.py` - protect Watchlist rendering and control-binding contracts.

**Session 58 (backend safety/correctness - Journal payloads and detail reads, §7.79):**
- `app/api/v1/journal.py` - normalize and bound Journal JSON before auto-P&L/ORM assignment, validate date/filter inputs, and add an ownership-scoped detail GET for editing.
- `tests/unit/test_journal_input_validation.py`, `tests/integration/test_journal_routes_validation.py` - cover malformed payloads, finite values, dates and detail reads.

**Session 59 (UI safety/correctness - Journal workflow, §7.80):**
- `frontend/templates/dashboard/journal.html` - escape table/insight values, bind entry actions through datasets, use detail reads for edits, correctly interpret delete responses, guard duplicate saves, and scope weekly notes by user.
- `tests/unit/test_journal_template_safety.py` - protect Journal rendering and mutation contracts.

### 7.81 IMPLEMENTED - Harden shared navigation and ticker controls

The shared navigation now uses delegated, keyboard-capable control bindings instead of inline handlers. Ticker visibility updates safely synchronize the icon, tooltip and ARIA state, while storage failures no longer break page initialization.

**Risk level:** High cross-page reliability and accessibility value, low compatibility risk. **Affected modules:** `frontend/templates/partials/base.html`, `frontend/static/js/app.js`, `tests/unit/test_shared_navigation_safety.py`. **Migration:** none.

**Regression evidence:** Shared navigation checks passed (**4 passed**), JavaScript parsing and whitespace validation passed. Commit: `a3ba4f9`.

### 7.82 IMPLEMENTED - Harden Backtesting workflow

Backtesting now validates user inputs before submission, ignores stale history/detail responses, safely renders provider data, suppresses duplicate history navigation, and keeps pagination usable for long histories. Result and upgrade states are bounded and escaped before they reach the DOM.

**Risk level:** High analytical trust and UI safety value, low API compatibility risk. **Affected modules:** `frontend/templates/dashboard/backtesting.html`, `tests/unit/test_backtesting_template_safety.py`. **Migration:** none.

**Regression evidence:** Backtesting checks passed (**6 passed**), extracted browser JavaScript parsing and whitespace validation passed. Commit: `cc1dfb3`.

### 7.83 IMPLEMENTED - Harden Signals workflow

Signals tabs, history, P&L, filters and pagination now use event delegation and safe rendering. Live/history requests reject stale responses, P&L refreshes cannot overlap, numeric fields are finite and bounded, and provider-controlled labels/details are escaped before rendering.

**Risk level:** High decision-support trust and performance value, low API compatibility risk. **Affected modules:** `frontend/templates/dashboard/signals.html`, `tests/unit/test_signals_template_safety.py`. **Migration:** none.

**Regression evidence:** Signals checks passed (**6 passed**), extracted browser JavaScript parsing and whitespace validation passed. Commit: `6087992`.

### 7.84 IMPLEMENTED - Harden Technical Analysis Summary

Technical Analysis Summary tabs and AI/EMA interactions now use delegated keyboard-capable controls. Asset, timeframe, rating, quote, AI and EMA payloads are validated and escaped, preventing malformed provider values from becoming selectors or executable markup.

**Risk level:** High decision-support trust and accessibility value, low API compatibility risk. **Affected modules:** `frontend/templates/dashboard/ta_summary.html`, `tests/unit/test_ta_summary_template_safety.py`. **Migration:** none.

**Regression evidence:** Technical Analysis checks passed (**6 passed**), extracted browser JavaScript parsing and whitespace validation passed. Commit: `f77979b`.

### 7.85 IMPLEMENTED - Harden Risk Manager boundaries

Risk calculation routes now reject non-finite, malformed and out-of-range values, including invalid ATR histories and price parameters. The Risk Manager UI validates calculation inputs, safely renders quick signals and portfolio-risk data, and removes inline action handlers without changing the existing API shape.

**Risk level:** Critical financial-safety value, low compatibility risk for valid requests. **Affected modules:** `app/api/v1/risk.py`, `frontend/templates/dashboard/risk.html`, `tests/integration/test_risk_routes.py`, `tests/unit/test_risk_template_safety.py`. **Migration:** none.

**Regression evidence:** Risk-focused checks passed (**48 passed**), Python and browser JavaScript parsing passed, and whitespace validation passed. Existing deprecation warnings remain for pandas/SQLAlchemy/Flask-Migrate and do not fail the suite. Commit: `bf7709c`.

### 7.86 IMPLEMENTED - Harden account Settings and profile updates

Account Settings controls now use delegated event listeners, escape user/plan/asset/2FA values, validate QR and backup-code payloads, and suppress repeated plan/2FA mutations. The profile API now requires an object body, enforces strict types and finite bounded financial settings, limits text fields, validates themes and password changes, and preserves the encrypted Telegram token when no replacement is supplied.

**Risk level:** Critical account-integrity and security value, low compatibility risk for valid requests. **Affected modules:** `frontend/templates/dashboard/settings.html`, `app/auth/routes.py`, `tests/integration/test_profile_routes_validation.py`, `tests/unit/test_settings_template_safety.py`. **Migration:** none.

**Regression evidence:** Profile/settings checks passed (**11 passed**), Python and browser JavaScript parsing passed, and whitespace validation passed. Existing deprecation warnings remain for pandas/SQLAlchemy/Flask-Migrate and do not fail the suite. Commit: `cba32a9`.

**Session 60 (UI security/accessibility - shared navigation and ticker controls, §7.81):**
- `frontend/templates/partials/base.html`, `frontend/static/js/app.js` - replace shared inline controls with delegated bindings and synchronize safe ticker state.
- `tests/unit/test_shared_navigation_safety.py` - protect shared navigation control wiring.

**Session 61 (UI security/performance - Backtesting workflow, §7.82):**
- `frontend/templates/dashboard/backtesting.html` - validate inputs, bound rendering, ignore stale reads and guard duplicate history actions.
- `tests/unit/test_backtesting_template_safety.py` - protect Backtesting control and rendering contracts.

**Session 62 (UI security/performance - Signals workflow, §7.83):**
- `frontend/templates/dashboard/signals.html` - harden tabs, history, P&L, filters, pagination and dynamic provider rendering.
- `tests/unit/test_signals_template_safety.py` - protect Signals control and rendering contracts.

**Session 63 (UI security/accessibility - Technical Analysis Summary, §7.84):**
- `frontend/templates/dashboard/ta_summary.html` - validate and escape AI/EMA/quote data and replace inline interactions.
- `tests/unit/test_ta_summary_template_safety.py` - protect Technical Analysis Summary controls.

**Session 64 (backend/UI financial safety - Risk Manager, §7.85):**
- `app/api/v1/risk.py` - reject malformed, non-finite and out-of-range risk inputs.
- `frontend/templates/dashboard/risk.html` - validate calculator inputs and safely render risk data without inline actions.
- `tests/integration/test_risk_routes.py`, `tests/unit/test_risk_template_safety.py` - cover route and UI risk boundaries.

**Session 65 (account security/UI safety - account Settings and profile updates, §7.86):**
- `app/auth/routes.py` - validate profile and password mutation payloads with strict types, bounds and secret-preserving behavior.
- `frontend/templates/dashboard/settings.html` - safely render account settings, plans and 2FA flows and serialize mutations.
- `tests/integration/test_profile_routes_validation.py`, `tests/unit/test_settings_template_safety.py` - cover authenticated profile validation and settings control contracts.

### 7.87 IMPLEMENTED - Harden admin Asset management

Admin asset create, update and add-from-search endpoints now require JSON objects, normalize symbols, validate market/source values, bound text and numeric fields, reject non-finite values, prevent empty updates, and handle uniqueness races without leaking database errors. The Assets page now uses delegated controls, bounded bulk concurrency, stale-response guards, safe provider rendering, and duplicate-mutation suppression for filtering, catalog, search, enable/disable and removal workflows.

**Risk level:** Critical platform configuration and data-integrity value, low compatibility risk for valid asset operations. **Affected modules:** `app/api/v1/assets.py`, `frontend/templates/admin/assets.html`, `tests/integration/test_asset_routes_validation.py`, `tests/unit/test_admin_assets_template_safety.py`. **Migration:** none.

**Regression evidence:** Asset route/UI checks passed (**10 passed**), Python and browser JavaScript parsing passed, inline handler audit passed, and whitespace validation passed. Existing deprecation warnings remain for pandas/SQLAlchemy/Flask-Migrate and do not fail the suite. Commit: `571f7a1`.

**Session 66 (admin data integrity/UI performance - Asset management, §7.87):**
- `app/api/v1/assets.py` - normalize and bound admin asset payloads, validate add-from-search values, and handle duplicate-write races.
- `frontend/templates/admin/assets.html` - replace inline controls, safely render provider values, sequence reads and bound bulk mutations.
- `tests/integration/test_asset_routes_validation.py`, `tests/unit/test_admin_assets_template_safety.py` - cover route and UI safety boundaries.

### 7.88 IMPLEMENTED - Harden Commodities market workflow

Commodity price, sentiment and signal displays now validate provider payloads, bound percentages and counts, reject unknown generation inputs, suppress duplicate generation, guard stale signal/sentiment reads, and expose working pagination. Cards and actions are keyboard-capable and no longer depend on inline handlers.

**Risk level:** High decision-support trust and user-experience value, low API compatibility risk. **Affected modules:** `frontend/templates/markets/commodities.html`, `tests/unit/test_commodities_template_safety.py`. **Migration:** none.

**Regression evidence:** Commodities checks passed (**3 passed**), browser JavaScript parsing and inline handler audit passed. Commit: `643f583`.

### 7.89 IMPLEMENTED - Harden AI Insights and model analytics surfaces

AI Insights now safely normalizes asset and prediction payloads, bounds probabilities/quality/history values, serializes one prediction run at a time, and prevents stale results from replacing a newer run. Model Performance now guards malformed analytics records, finite numeric displays, chart-library absence and duplicate refreshes. Signal Analytics now safely renders provider aggregates, bounds counts/rates, protects chart lifecycle and uses dataset-bound exports.

**Risk level:** Critical decision-support trust and observability value, low API compatibility risk. **Affected modules:** `frontend/templates/dashboard/ai_insights.html`, `frontend/templates/dashboard/model_performance.html`, `frontend/templates/dashboard/analytics.html`, `tests/unit/test_ai_insights_template_safety.py`, `tests/unit/test_model_performance_template_safety.py`, `tests/unit/test_analytics_template_safety.py`. **Migration:** none.

**Regression evidence:** AI Insights, Model Performance and Analytics checks each passed (**3 passed each**), rendered JavaScript parsing passed, and inline handler audits passed. Commits: `a712b49`, `060f9b9`, `260e5a7`.

**Session 67 (UI safety/performance - Commodities market workflow, §7.88):**
- `frontend/templates/markets/commodities.html` - validate commodity payloads, guard reads/generation, remove inline controls and add pagination.
- `tests/unit/test_commodities_template_safety.py` - protect commodity rendering and action contracts.

**Session 68 (UI safety/decision-support integrity - AI Insights and Model Performance, §7.89):**
- `frontend/templates/dashboard/ai_insights.html` - bound model values, escape asset/prediction metadata and guard concurrent runs.
- `frontend/templates/dashboard/model_performance.html` - bound analytics values, protect chart fallback and serialize refreshes.
- `tests/unit/test_ai_insights_template_safety.py`, `tests/unit/test_model_performance_template_safety.py` - protect both analytical screens.

**Session 69 (UI safety/performance - Signal Analytics, §7.89):**
- `frontend/templates/dashboard/analytics.html` - safely render aggregate values, protect chart lifecycle, serialize refreshes and bind exports without inline handlers.
- `tests/unit/test_analytics_template_safety.py` - protect the Analytics rendering and export contract.

### 7.90 IMPLEMENTED - Harden Broker Connections and credential handling

Broker connection management now validates provider identity and credential shape at the API boundary, normalizes provider names, supports API-key-only providers correctly, encrypts accepted credentials and handles concurrent uniqueness races without exposing database errors. The Broker Connections page now safely escapes catalog and connection data, validates documentation URLs, delegates controls, guards stale reads, prevents duplicate connect/test/disconnect mutations, handles failed responses accurately and supports keyboard/form submission without inline handlers.

**Risk level:** Critical credential-security, financial-safety and account-integrity value, low compatibility risk for valid broker connections. **Affected modules:** `app/api/v1/trading.py`, `app/services/trading/broker_registry.py`, `frontend/templates/dashboard/broker_connections.html`, `tests/integration/test_broker_connection_validation.py`, `tests/unit/test_broker_connections_template_safety.py`. **Migration:** none.

**Regression evidence:** Broker connection checks passed (**8 passed**), Python compilation and extracted browser JavaScript parsing passed, and whitespace validation passed. Existing deprecation warnings remain for pandas/SQLAlchemy/Flask-Migrate and do not fail the suite. Commit: `c5988f7`.

**Session 70 (credential security/UI reliability - Broker Connections, §7.90):**
- `app/api/v1/trading.py`, `app/services/trading/broker_registry.py` - normalize providers, bound credential input, support API-key-only providers and handle duplicate writes safely.
- `frontend/templates/dashboard/broker_connections.html` - replace inline broker actions, escape dynamic catalog/connection data, guard stale reads and duplicate mutations, and submit the modal through its form.
- `tests/integration/test_broker_connection_validation.py`, `tests/unit/test_broker_connections_template_safety.py` - cover API credential boundaries and browser control contracts.

### 7.91 IMPLEMENTED - Harden News filters and refresh lifecycle

The public News endpoint now accepts only the supported sentiment filters and normalizes them before querying. The News page delegates pagination, bounds rendered collections, safely handles malformed provider payloads and time values, prevents stale filtered responses from replacing newer results, and avoids overlapping background polling or duplicate refresh timers.

**Risk level:** High decision-support trust and public-endpoint reliability value, low compatibility risk for supported filters and valid news data. **Affected modules:** `app/api/v1/news.py`, `frontend/templates/dashboard/news.html`, `tests/integration/test_news_input_validation.py`, `tests/unit/test_news_template_safety.py`. **Migration:** none.

**Regression evidence:** News UI, filter and fetch-throttle checks passed (**9 passed**), Python and browser JavaScript parsing passed, and whitespace validation passed. Existing deprecation warnings remain for pandas/SQLAlchemy/Flask-Migrate and do not fail the suite. Commit: `8b91988`.

**Session 71 (public API/UI reliability - News, §7.91):**
- `app/api/v1/news.py` - validate and normalize sentiment query filters.
- `frontend/templates/dashboard/news.html` - replace inline pagination, bound news/calendar rendering, guard stale refreshes and serialize polling/timers.
- `tests/integration/test_news_input_validation.py`, `tests/unit/test_news_template_safety.py` - cover News query boundaries and browser refresh/control contracts.

### 7.92 IMPLEMENTED - Harden Dhan indices and options workflow

Dhan endpoints now canonicalize supported underlyings, reject unknown or empty index selections, validate non-expired ISO expiry dates and prevent malformed requests from reaching the provider. The indices/options page now safely renders quote and chain values, bounds provider collections, validates dates, serializes refreshes, and ignores stale status/quote/expiry/chain responses.

**Risk level:** High external-provider reliability and decision-support integrity value, low compatibility risk for valid Dhan inputs. **Affected modules:** `app/api/v1/dhan.py`, `frontend/templates/dashboard/dhan_indices.html`, `tests/integration/test_dhan_input_validation.py`, `tests/unit/test_dhan_template_safety.py`. **Migration:** none.

**Regression evidence:** Dhan API/UI checks passed (**10 passed**), Python and browser JavaScript parsing passed, and whitespace validation passed. Existing deprecation warnings remain for pandas/SQLAlchemy/Flask-Migrate and do not fail the suite. Commit: `2a2149e`.

**Session 72 (external data safety/UI reliability - Dhan indices and options, §7.92):**
- `app/api/v1/dhan.py` - canonicalize underlying names, bound index selections and validate option expiry dates before provider access.
- `frontend/templates/dashboard/dhan_indices.html` - validate and escape quote/chain payloads, bound rows and serialize status/refresh requests.
- `tests/integration/test_dhan_input_validation.py`, `tests/unit/test_dhan_template_safety.py` - cover Dhan request boundaries and browser rendering contracts.

### 7.93 IMPLEMENTED - Harden Advanced Analysis dashboard

Advanced Analysis now validates configured timeframes at the API boundary and reuses its short-lived computed payload cache. The dashboard safely normalizes candle and provider-derived analysis values, bounds chart/panel collections, deduplicates chart timestamps, ignores stale or duplicate requests, uses delegated accessible controls, makes FVG and Order Block toggles functional, and adapts chart/panel sizing on smaller screens.

**Risk level:** Critical decision-support integrity and usability value, low compatibility risk for valid timeframes and existing analysis responses. **Affected modules:** `app/api/v1/market_data.py`, `frontend/templates/dashboard/advanced_analysis.html`, `tests/integration/test_advanced_analysis_validation.py`, `tests/unit/test_advanced_analysis_template_safety.py`. **Migration:** none.

**Regression evidence:** Advanced Analysis checks passed (**7 passed**), Python compilation and extracted browser JavaScript parsing passed, and whitespace validation passed. Existing pandas/SQLAlchemy/Flask-Migrate deprecation warnings and the local pytest cache permission warning remain non-blocking. Commit: `8db011d`.

**Session 73 (decision-support UI/API reliability - Advanced Analysis, §7.93):**
- `app/api/v1/market_data.py` - reject unsupported Advanced Analysis timeframes before provider access.
- `frontend/templates/dashboard/advanced_analysis.html` - harden chart/panel rendering, request sequencing, accessibility, responsive sizing and zone toggles.
- `tests/integration/test_advanced_analysis_validation.py`, `tests/unit/test_advanced_analysis_template_safety.py` - cover timeframe boundaries and browser rendering/control contracts.

**Database changes:** additive nullable columns were added to `signals` for data-quality context and, in §7.29, signal provenance; Backtest rows gained additive cost, reproducibility and risk fields; §7.31 adds an additive nullable `predictions.model_version` column, §7.32 adds nullable `predictions.data_quality` JSON, and §7.33 adds nullable `predictions.model_outputs` JSON. **API contract changes:** additive metadata only — `POST /backtesting/run`, `Signal.to_dict()`, and `Prediction.to_dict()` gained fields; the prediction endpoint can return the existing warming-up status more accurately when the predictor falls back. No field was removed or renamed. Phase 3 adds a new internal gate to `generate_signal()` that can return `None` (no signal) in cases that previously would have produced one — specifically only when data is stale (live path only) or corrupt (both live and backtest) — no existing route, response shape, or subscription rule changed. §7.36 changes only row ordering and targeted cache invalidation. **No destructive migration. No new credentials or secrets introduced.**

### 7.94 IMPLEMENTED - Reorganize the primary dashboard information architecture

The shared Flask/Jinja shell now presents eight task-oriented navigation groups: Overview, Markets, Signals & Discovery, AI & Analysis, Research, Portfolio, Account, and Admin. Dhan indices/options is grouped with Markets, Backtesting and Signal Analytics are grouped under Research, AI Insights is grouped with analysis, and settings/help are grouped under Account. Admin-only Auto Generate remains hidden behind the existing role check, and existing route paths, active-state values, tier gates, and JavaScript element IDs were preserved.

**Risk level:** High discoverability and workflow clarity value, low compatibility risk because route contracts and authorization behavior are unchanged. **Affected modules:** `frontend/templates/partials/base.html`, `tests/unit/test_shared_navigation_safety.py`. **Migration:** none.

**Regression evidence:** Shared navigation checks passed (**2 passed**), the Jinja template parsed successfully, the eight-group and route-placement assertions passed, and whitespace validation passed. Existing local pytest cache permission and unrelated working-tree warnings remain non-blocking. Commit: `bd92c42`.

**Session 74 (information architecture - primary dashboard shell, §7.94):**
- `frontend/templates/partials/base.html` - align sidebar groups to user tasks, remove cross-group duplication, preserve active states/tier gates, and keep admin-only controls hidden.
- `tests/unit/test_shared_navigation_safety.py` - protect group count, group naming, route placement, active-group coverage, and unique account controls.
- `docs/UI0_DISCOVERY.md` - source inventory and route/API/component baseline used to select the IA changes.

**Database changes:** none. **API contract changes:** none. **No new credentials or secrets introduced.**

### 7.99 IMPLEMENTED - Improve the primary dashboard decision surface

The dashboard now distinguishes current market conditions, live active signals, today's UTC activity and historical closed-trade performance in the interface itself. A compact data-context bar reports refresh state and last update time, the equity range accurately says it is limited to the latest 100 closed trades, chart/table regions have accessible descriptions, and heatmap metrics expose a complete tab/tabpanel relationship. Refreshes are serialized, stale signal and heatmap responses are ignored, provider numbers are normalized and bounded before rendering, charts retain recoverable empty states, and partial API failures are reported instead of leaving indefinite loading placeholders.

**Risk level:** High decision-support clarity, accessibility and perceived-performance value, low compatibility risk because existing API paths, response shapes, navigation targets and table/chart IDs are preserved. **Affected modules:** `frontend/templates/dashboard/index.html`, `frontend/static/js/pages/dashboard.js`, `frontend/static/css/main.css`, `tests/unit/test_dashboard_template_safety.py`. **Migration:** none.

**Regression evidence:** Dashboard safety/accessibility checks passed (**6 passed**), dashboard JavaScript syntax validation passed, the Jinja template parsed successfully, and whitespace validation passed. Existing local pytest cache permission and unrelated working-tree warnings remain non-blocking. Commit: pending.

**Session 79 (dashboard UX, data freshness and resilient rendering - UI-6, §7.99):**
- `frontend/templates/dashboard/index.html` - label live/current versus historical/UTC dashboard data, improve action and chart/table semantics, and add a complete heatmap tab relationship.
- `frontend/static/js/pages/dashboard.js` - serialize full refreshes, ignore stale responses, expose degraded states, normalize provider numbers, preserve chart recovery and bound live rendering.
- `frontend/static/css/main.css` - add responsive dashboard data-context status styling using the shared design tokens.
- `tests/unit/test_dashboard_template_safety.py` - protect dashboard scope labels, ARIA relationships, refresh coordination, stale-response handling and numeric/chart safeguards.

**Database changes:** none. **API contract changes:** none. **No new credentials or secrets introduced.**

### 7.97 IMPLEMENTED - Improve the public/pre-login experience

The public landing page now has skip navigation, semantic public navigation and a real mobile menu instead of hiding all navigation links on small screens. The page exposes a main landmark, explicit live-price region, keyboard focus treatment and reduced-motion behavior. Public ticker, sentiment, social-link, stats and signal-preview payloads are now bounded, validated, escaped or DOM-rendered safely; ticker polling is serialized and its timeout is always released. Blocked browser storage falls back without breaking the page.

**Risk level:** High conversion, accessibility and public-data trust value, low compatibility risk because existing public routes, content sections and API response shapes are preserved. **Affected modules:** `frontend/templates/landing.html`, `tests/unit/test_public_landing_safety.py`. **Migration:** none.

**Regression evidence:** Public landing checks passed (**3 passed**), four inline scripts passed Node parsing, the main landmark is balanced, and whitespace validation passed. Existing local pytest cache permission and unrelated working-tree warnings remain non-blocking. Commit: `02ff250`.

**Session 77 (public UX and safe rendering - UI-4, §7.97):**
- `frontend/templates/landing.html` - add responsive public navigation, skip link, main landmark, focus/reduced-motion behavior, storage safety, serialized ticker polling and bounded/escaped public data rendering.
- `tests/unit/test_public_landing_safety.py` - protect public navigation, live-data safety, error handling and polling contracts.

**Database changes:** none. **API contract changes:** none. **No new credentials or secrets introduced.**

### 7.96 IMPLEMENTED - Harden the shared application shell

The authenticated shell now exposes explicit labels and relationships for the sidebar, application toolbar, mobile navigation, command palette, notifications, theme control, ticker, and Ask AI widget. The command palette now behaves as a keyboard-accessible dialog with `aria-hidden` state, focus cycling, Escape handling and focus restoration. Mobile navigation and Ask AI keep their expanded/hidden state synchronized with the DOM. First-paint and runtime preference storage are guarded so blocked browser storage falls back safely.

**Risk level:** Critical accessibility and cross-device usability value, low compatibility risk because route destinations, data contracts and existing element IDs are unchanged. **Affected modules:** `frontend/templates/partials/base.html`, `frontend/static/js/global_ask_ai.js`, `tests/unit/test_application_shell_safety.py`. **Migration:** none.

**Regression evidence:** Application-shell, design-system and navigation checks passed (**6 passed**), both global JavaScript files passed Node syntax checks, the base inline scripts parsed successfully, the base Jinja template parsed successfully, and whitespace validation passed. Existing local pytest cache permission and unrelated working-tree warnings remain non-blocking. Commits: `baf4799`, `caa142a`.

**Session 76 (shared shell accessibility and resilience - UI-3, §7.96):**
- `frontend/templates/partials/base.html` - add shell landmarks, explicit control names, modal relationships, and storage-safe first-paint preference handling.
- `frontend/templates/partials/base.html` - add keyboard focus cycling and opener focus restoration for the command palette.
- `frontend/static/js/global_ask_ai.js` - synchronize Ask AI popup ARIA state and restore focus after close.
- `tests/unit/test_application_shell_safety.py` - protect shell semantics, keyboard behavior and storage/overlay state contracts.

**Database changes:** none. **API contract changes:** none. **No new credentials or secrets introduced.**

### 7.95 IMPLEMENTED - Establish the shared UI design-system foundation

The primary dashboard stylesheet now exposes semantic surface, status, focus, control-size, motion and layering tokens while retaining the existing `--bg-*` compatibility aliases. Shared primitives cover elevated surfaces, responsive toolbars, loading/empty/error states, horizontally safe data tables, semantic chips, tabular metrics and visually hidden accessible text. The authenticated shell now opts into an explicit color scheme, applies a consistent keyboard focus ring and disables motion/hover transforms when the user requests reduced motion.

**Risk level:** High consistency, accessibility and implementation-speed value, low compatibility risk because the token/primitives layer is additive and existing page classes remain supported. **Affected modules:** `frontend/static/css/main.css`, `frontend/templates/partials/base.html`, `tests/unit/test_design_system_safety.py`. **Migration:** none.

**Regression evidence:** Design-system and shared-shell checks passed (**4 passed**), the base Jinja template parsed successfully, and whitespace validation passed. Existing local pytest cache permission and unrelated working-tree warnings remain non-blocking. Commit: `f3cadb8`.

**Session 75 (design system and accessibility foundation - UI-2, §7.95):**
- `frontend/static/css/main.css` - add semantic tokens, reusable surfaces/toolbars/states/chips/metrics, focus treatment, responsive state layout, and reduced-motion behavior.
- `frontend/templates/partials/base.html` - mark the authenticated shell with the shared `app-shell` hook.
- `tests/unit/test_design_system_safety.py` - protect token, primitive, focus, color-scheme and reduced-motion contracts.

**Database changes:** none. **API contract changes:** none. **No new credentials or secrets introduced.**

### 7.98 IMPLEMENTED - Unify the authentication and onboarding experience

Login, registration and password recovery now share one read-only public market-context controller instead of maintaining three drifting ticker and statistics implementations. Auth forms use explicit labels, semantic landmarks, live feedback regions and stateful hidden/visible relationships; login 2FA, registration, recovery, reset and email verification transitions expose their state to assistive technology. Network failures, malformed responses, blocked browser storage and request timeouts now recover with bounded user-facing feedback without changing auth endpoints or token contracts.

**Risk level:** High trust, accessibility and conversion value, low compatibility risk because existing routes, API payloads, form IDs, token keys and security-neutral recovery messaging are preserved. **Affected modules:** `frontend/templates/partials/base.html`, `frontend/static/js/auth_public.js`, `frontend/templates/auth/login.html`, `frontend/templates/auth/register.html`, `frontend/templates/auth/forgot_password.html`, `frontend/templates/auth/reset_password.html`, `frontend/templates/auth/verify_email.html`, `tests/unit/test_auth_experience_safety.py`. **Migration:** none.

**Regression evidence:** Auth UI contract checks passed (**3 passed**); existing profile mutation and new-IP-login security integration checks passed (**10 passed**); browser JavaScript syntax checks, auth template parsing and whitespace validation passed. Existing pandas/SQLAlchemy/Flask-Migrate deprecation warnings and the local pytest cache permission warning remain non-blocking. Commit: pending.

**Session 78 (authentication UX, onboarding resilience and shared public context - UI-5, §7.98):**
- `frontend/templates/partials/base.html` - load the shared auth-only public context controller without exposing authenticated-only widgets on pre-login screens.
- `frontend/static/js/auth_public.js` - consolidate bounded, DOM-safe ticker/stat rendering with timeout cleanup and unavailable states.
- `frontend/templates/auth/login.html`, `register.html`, `forgot_password.html`, `reset_password.html`, `verify_email.html` - add form relationships, landmarks, live feedback and resilient submit/state transitions while preserving endpoint contracts.
- `tests/unit/test_auth_experience_safety.py` - protect auth labels, state transitions, shared rendering, storage and response-handling contracts.

**Database changes:** none. **API contract changes:** none. **No new credentials or secrets introduced.**
