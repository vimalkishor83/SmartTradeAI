# SmartTrade AI — Improvement Audit

**Status:** Living document. Started as Phase 0 of a structured production-hardening pass; updated as each subsequent phase's investigation and fixes land. Every entry below is based on reading the actual code and, where marked, verifying behavior live on the production server — not on the platform's design intent or documentation claims.

**Last updated:** 2026-09-05 (Phase 0 + Phase 1 pass)

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

### 2.6 NOT YET FIXED — Partial-TP double-counting in the strategy-config engine

`app/services/backtesting/engine.py` (the *other* backtest engine, used by `POST /api/v1/backtesting/run`, not the walk-forward "Live Engine") appends a separate `trades` list entry for a T1 partial exit (line ~254, `outcome: "win"/"loss"`) **in addition to** the eventual full-close entry for the same underlying signal (lines ~274-286 / ~333-340). One live position can therefore become two rows in `_compute_stats`'s trade list, inflating both `total_trades` and the win/loss counts for what was actually a single trade. This does not itself produce a value outside 0-100% (win_rate is still `wins/total`, which stays bounded), but it does skew the *accuracy* of the reported win rate and total-trade count whenever a strategy uses partial take-profits.

**Risk level:** Medium (silent statistical skew, not a crash or an impossible value — harder for a user to notice than the >100% bug, but affects trust in the "Multi-Indicator"/"EMA Crossover"/etc. strategy backtests specifically). **Affected modules:** `app/services/backtesting/engine.py`. **Proposed fix (not yet implemented):** track partial exits as a running-total adjustment on the *same* trade record rather than a separate list entry, only appending one final row per opened position once it's fully closed. **Migration:** none required (in-memory calculation change only, no schema impact) — needs careful test coverage before changing, since it affects every existing strategy-config backtest's reported numbers.

### 2.7 NOT A BUG — Look-ahead bias / future-data leakage

Explicitly checked and found correctly guarded in both engines: `runner.py` computes signals from `df.iloc[:i+1]` and only simulates outcomes on `df.iloc[i+1:]`; `engine.py` uses an equivalent `df_r.iloc[max(0,i-warmup):i+1]` windowing with position management strictly on future bars. Duplicate/re-entrant signal execution is blocked via bar-skip logic (`i += max(step, max_bars)` in `runner.py`; `last_close_bar`/`position is None` checks in `engine.py`). No changes made or needed here.

### 2.8 MINOR — Walk-forward window averaging unweighted by trade count

`app/services/backtest/walk_forward.py` averages `win_rate` across windows via unweighted `np.mean(win_rates)` rather than pooling trades first. A window with 3 trades and a window with 50 trades currently count equally toward the average. Not a >100% bug; a minor statistical-quality issue. **Risk level:** Low. **Not fixed this pass** — flagged for a future Phase 1 follow-up.

---

## 3. Remaining P0/P1 items from the full 16-phase spec (not started)

This audit and the fixes above cover Phase 0 (discovery) and the highest-priority item of Phase 1 (win-rate correctness + its immediately adjacent display bugs). The full spec's remaining phases are substantial, multi-week-scale work and have **not** been started:

- Phase 1 (remainder): commission/slippage/spread modeling audit, Sharpe/Sortino/recovery-factor calculation audit, reproducibility metadata (backtest ID, engine version, model version) on every result, the partial-TP double-counting fix (§2.6).
- Phase 2: AI confidence/calibration architecture, Evidence/Counter-Evidence UI in AI Decision Inspector.
- Phase 3: Data Quality engine (GREEN/YELLOW/RED provider health states).
- Phase 4: Signal-lifecycle metadata/versioning.
- Phases 5–16: as specified, untouched.

Each should get its own investigation-then-fix pass with the same evidence-based discipline used here (read the actual code, verify claims against real behavior, add regression tests, verify live before calling it done) rather than being implemented speculatively in one large batch.

---

## 4. Files changed this pass

- `frontend/templates/dashboard/backtesting.html` — win-rate double-multiplication fix, `sample_trades`/`trades_data` key fix, zero-trade empty state, min-sample-size warning.
- `app/api/v1/signals.py` — `sample_trades`/`trades_data` key fix in the `/signals/backtest` trade-normalization loop.
- `tests/unit/test_backtest_win_rate.py` — new, 9 tests.
- `docs/IMPROVEMENT_AUDIT.md` — this file.

**Database changes:** none. **API contract changes:** none (response schemas unchanged; only which existing fields the consumers read was fixed). **No destructive migration. No new credentials or secrets introduced.**
