# SmartTrade AI Architecture Map

**Status:** Phase 0 baseline
**Last reviewed:** 2026-09-05

This document describes the implementation that exists in the repository. It is not a product wish-list. Items described as planned are intentionally not treated as available functionality.

## Runtime Shape

```text
Browser
  |
  +--> Flask server-rendered dashboard (`frontend/templates`)
  +--> Vanilla terminal shell (`frontend-Terminal`, mounted at `/terminal`)
  |
  +--> Flask API (`/api/v1/*`)
          |
          +--> Auth/RBAC (`app/auth`)
          +--> Domain services (`app/services`)
          +--> SQLAlchemy models (`app/models`)
          +--> PostgreSQL / SQLite development database
          +--> Redis cache and rate-limit storage
          +--> Socket.IO events (`app/websocket`)

Worker process (`worker.py`)
  +--> APScheduler jobs (`app/tasks`)
  +--> Market-data stream and scheduled signal/notification work
```

Production uses separate `app` and `worker` containers. The web process runs with `RUN_SCHEDULER=0`; the worker owns scheduled jobs and the market stream. PostgreSQL and Redis are separate Compose services.

## Frontend

| Surface | Location | Responsibility |
|---|---|---|
| Shared dashboard shell | `frontend/templates/partials/base.html` | Sidebar, topbar, shared assets, theme bootstrap, page blocks |
| Dashboard pages | `frontend/templates/dashboard`, `frontend/templates/markets` | Jinja page structure and page-specific scripts/styles |
| Dashboard behavior | `frontend/static/js` | Page controllers, API calls, charts, settings, admin workflows |
| Dashboard styling | `frontend/static/css/main.css` | Shared design tokens and page styles |
| Terminal SPA | `frontend-Terminal` | Separate hash-routed vanilla-JS terminal, shared `/api/v1` backend |

The two frontend surfaces are additive but not one design system yet. The terminal has its own CSS tokens and component modules; the dashboard has a much larger shared stylesheet and server-rendered navigation.

## Backend Boundaries

| Area | Location | Notes |
|---|---|---|
| App factory and registration | `app/__init__.py` | Extensions, blueprints, database seed/migrations, scheduler, logging, stream startup |
| Configuration | `app/config.py`, `.env.example` | Environment-driven secrets, database, Redis, JWT, CORS, rate limits |
| Page routes | `app/views.py` | Server-rendered page selection and access flags |
| Authentication | `app/auth/routes.py` | Registration, login, refresh/logout, 2FA, profile, account deletion |
| Authorization | `app/auth/decorators.py` | JWT validity, approval status, role, super-admin, tier and feature gates |
| API routes | `app/api/v1` | Signals, market data, assets, backtests, portfolio, watchlists, admin, notifications, trading and analytics |
| Persistence | `app/models`, `migrations/versions` | SQLAlchemy models plus Alembic history |
| Market data | `app/services/data` | Provider fetchers, caching, quality checks, Delta stream, bulk fetching |
| Analysis | `app/services/indicators`, `app/services/signals` | Indicator calculations, pattern/MTF analysis, signal engine and reasoning |
| AI/ML | `app/services/ai` | Model prediction, fallback behavior and LLM reasoning integration |
| Backtesting | `app/services/backtest`, `app/services/backtesting` | Two distinct engines: live-engine walk-forward and strategy-config backtesting |
| Risk and portfolio | `app/services/risk`, `app/api/v1/portfolio.py`, `app/models/portfolio.py` | Risk calculations, positions, portfolio state and broker-facing operations |
| Operations | `app/api/v1/system.py`, `app/services/error_tracking.py`, logging in `app/__init__.py` | Health/readiness, logs, Sentry wrapper and audit events |
| Background work | `app/tasks`, `worker.py` | Signal generation, outcome closure, data collection, notifications and protective orders |

## Important Data Flows

### Signal flow

```text
Provider fetch
  -> data quality assessment
  -> indicator/pattern calculation
  -> signal engine gates and scoring
  -> Signal persistence
  -> notification delivery
  -> scheduled outcome evaluation
  -> SignalHistory / analytics
```

### Backtest flow

There are two intentionally different paths:

1. `GET /api/v1/signals/backtest` uses `app/services/backtest/runner.py` and replays the live signal engine over historical windows.
2. `POST /api/v1/backtesting/run` uses `app/services/backtesting/engine.py` and a named strategy configuration.

`app/services/backtesting/walk_forward.py` evaluates the second engine across sequential windows. These paths have different response schemas and must not be silently merged without a compatibility contract.

## Verified Strengths

- App and worker scheduling are separated in production Compose configuration.
- JWT sessions can be revoked through persisted `UserSession` rows.
- Admin destructive actions have a separate `is_super_admin` gate.
- Market data has a centralized quality assessment and signal-generation gate.
- Signal closure uses conditional claiming to prevent duplicate outcome writes.
- Backtesting has regression coverage for win-rate bounds, partial exits, and walk-forward aggregation.
- Health and readiness probes are unauthenticated and distinguish hard dependencies from soft market-stream status.

## Current Architectural Risks

- Dashboard and terminal are parallel frontend systems with duplicated navigation and presentation patterns.
- API responses are not yet standardized under one envelope or request-id contract.
- Confidence, model output, calibration, model agreement, regime compatibility and signal quality are not yet separate persisted concepts everywhere.
- ML model metadata and dataset/feature versions are not consistently persisted with predictions/signals.
- Portfolio and backtest domains need a systematic currency, reproducibility and metric-contract audit.
- The large app factory contains initialization, migrations, seeding, scheduling and logging responsibilities that should be separated gradually behind compatibility-preserving modules.
- The repository has no complete frontend build/test/E2E pipeline for either frontend surface.

## Boundary Rules For Future Work

- Domain calculations belong in services, not templates or route handlers.
- API handlers validate and authorize; they should not duplicate market, signal, portfolio or metric rules.
- New behavior must preserve existing response fields unless a versioned compatibility plan exists.
- New AI claims require repository evidence, tests and a measurable live verification path.
- No migration or infrastructure addition should be made without a concrete data or operational requirement.
