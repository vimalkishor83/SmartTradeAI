# SmartTrade AI UI-0 Discovery

**Phase:** UI-0 - Complete application discovery  
**Audit date:** 2026-09-06  
**Scope:** `D:\Claude\SmartTradeAI` only  
**Status:** Complete inventory baseline; no runtime redesign changes in this phase

## Method

This inventory was built from repository evidence, not from a hardcoded product list:

- Flask page routes in `app/views.py` and alternate frontend routes in `app/frontends.py`.
- API route decorators in `app/api/v1/*.py` plus blueprint registration in `app/__init__.py`.
- All Jinja templates under `frontend/templates`.
- Dashboard controllers under `frontend/static/js` and the `/terminal` SPA under `frontend-Terminal`.
- Shared styles, chart libraries, API clients, auth/role decorators, current tests and existing audit documents.

Counts at this baseline:

- 50 server-rendered Jinja templates, including shared/legal/auth templates.
- 41 user/admin-facing page routes in `app/views.py`, plus root/SEO/legal/auth routes.
- 3 alternate frontend route families: `/terminal`, `/new1`, `/new2`.
- 24 API blueprints and 177 route decorator entries, excluding the frontend page routes.
- 6 standalone dashboard page controllers in `frontend/static/js/pages` plus page-local scripts.
- 34 terminal registry modules, of which 17 are wired to real renderers and 17 are intentionally stubbed in the registry.

## Runtime Architecture

| Surface | Actual location | Route | Rendering/state model | Current role | Decision |
|---|---|---|---|---|---|
| Primary dashboard | `frontend/templates` and `frontend/static` | `/` page routes | Flask/Jinja plus vanilla page scripts; JWT API calls | Main authenticated product surface | Keep as canonical during UI migration |
| Terminal SPA | `frontend-Terminal` | `/terminal/` | Hash router, ES modules, local state and separate CSS/components | Alternate analytical workspace | Keep, but align its shell and contracts with primary surface |
| New1 alternate shell | Missing `frontend-New1` directory | `/new1/` | Flask static SPA fallback | Registered but not deployable from this checkout | Remove route or restore a real source before exposing it |
| New2 alternate shell | Missing `frontend-New2` directory | `/new2/` | Flask static SPA fallback | Registered but not deployable from this checkout | Remove route or restore a real source before exposing it |
| API | `app/api/v1` | `/api/v1/*` | Flask blueprints, JWT/RBAC/tier decorators | Shared data and mutation boundary | Preserve contracts; add canonical adapters only when needed |

### Access model finding

Most page routes return a page shell and rely on shared JavaScript plus API authorization/tier checks. Admin page routes use `page_admin_required`. The API is the authoritative security boundary. A visible or hidden navigation item must never be treated as authorization.

## Page Route Matrix

The status column reflects static repository inspection and existing tests. It is not a claim that every live provider is currently available.

| Route | Access | Page | Group | Purpose / primary user | Primary action | Data sources | Status | UX / duplicate finding | Missing states | Recommendation |
|---|---|---|---|---|---|---|---|---|---|---|
| `/` | Public | Redirect | Overview | Send visitors to the landing page | Follow redirect | Flask redirect | Working | No issue; root is not a product view | None | Keep |
| `/home` | Public | Landing | Public | Explain product and convert visitors | Register or sign in | Public config and optional preview API | Working | Separate public shell and terminal home repeat conversion language | Provider/API failure is intentionally soft | Improve after shell decision |
| `/login` | Public | Login | Account | Authenticate existing users | Sign in | `/auth/login`, `/auth/me` | Working | Jinja auth flow differs from terminal login gate | Rate-limit, locked, unverified and expired-session detail should be consistent | Improve and consolidate copy |
| `/register` | Public | Registration | Account | Create pending account | Register | `/auth/register`, brokers/referral checks | Working | Registration contains broker onboarding logic that belongs in a progressive flow | Pending approval, duplicate account and provider failure | Improve |
| `/forgot-password` | Public | Forgot password | Account | Start recovery | Request reset | `/auth/forgot-password` | Working | Standalone flow has a separate visual language | Rate-limit and non-enumerating confirmation | Improve |
| `/reset-password` | Public | Reset password | Account | Set a new password | Submit reset | `/auth/reset-password` | Working | Token-expired state needs consistent account shell | Invalid/expired token | Improve |
| `/verify-email` | Public | Verify email | Account | Verify account email | Verify/resend | `/auth/verify-email`, `/auth/resend-verification` | Working | Separate page with limited context | Expired token, already verified, resend limit | Improve |
| `/markets/<market>` | Crypto public; other markets Basic+ | Market overview | Markets | Review a market and its assets | Change market/asset or inspect signals | Market heatmap, signals, AI summary, news, calendar | Working | Same concept overlaps `commodities.html`, `terminal`, asset detail and market scripts | Stale/partial feed, no data, tier denied | Consolidate behind shared Market Experience |
| `/markets/commodities` | Basic+ shell | Commodities | Markets | Review commodity prices and generated signals | Refresh or generate analysis | `/assets`, market data, news, signals | Working | Duplicate market overview architecture and terminology | Provider unavailable, partial assets, stale prices | Merge into shared market-page system |
| `/markets/terminal` | Basic+ | Terminal | Markets | Advanced market workspace | Select asset and inspect chart/context | Market data and signals via page script | Partial | Competes with `/terminal/` SPA and Advanced Analysis | Permission, data freshness, no-signal, degraded provider | Merge or clearly differentiate |
| `/dhan-indices` | Authenticated API; page shell | Dhan indices/options | Markets | Review Indian index and option-chain data | Load chain | `/dhan/status`, `/dhan/indices`, `/dhan/options/*` | Working | Specialized flow is separate from market/index experience | Dhan unavailable, delayed chain, empty expiry | Keep as integration view; align shell |
| `/scanner` | Premium+ | Market Scanner | Signals | Discover assets matching filters | Run scan and save/add watchlist | `/scanner/filters`, `/scanner/run`, watchlist | Working | Overlaps Delta scanners and market signal filters | No matches, stale results, scan timeout | Consolidate filter model, keep specialized engines |
| `/delta-scanner` | Premium+ | Delta Scanner | Signals | Scan Delta market data | Run scanner and inspect results | Delta scanner endpoints, watchlist | Working | Specialized scanner duplicates scanner concepts and filter controls | Feed paused, partial results, retry | Keep as advanced provider-specific mode |
| `/delta-bubbles` | Premium+ | Delta Bubbles | Signals | Visualize Delta market activity | Change group/refresh | Delta bubbles endpoint | Working | Visualization is unique but uses a separate page controller | Unavailable feed, empty group, stale timestamp | Improve and reuse market freshness state |
| `/backtesting` | Authenticated; feature-gated API | Backtesting | Research | Test a strategy over historical data | Configure and run backtest | `/backtesting`, `/backtesting/run`, `/signals/backtest` | Working | Two backend engines and two result concepts are exposed in adjacent UI | Invalid assumptions, no trades, running/failed/partial, reproducibility | Keep both until contracts are reconciled; redesign flow |
| `/portfolio` | Authenticated | Portfolio | Portfolio | Review holdings and allocation | Add/update/remove holding | `/portfolio/*`, tickers | Working | Portfolio, Trading and Performance concepts are split without a shared summary | Broker disconnected, empty portfolio, currency/valuation stale | Consolidate portfolio workspace |
| `/watchlist` | Authenticated | Watchlist | Portfolio | Track selected assets | Add/remove/reorder | `/watchlist/*`, context, live prices | Working | Watchlist is also used by scanners and auto-generation with different interaction patterns | Empty, asset unavailable, stale context | Keep domain; share AssetSelector and freshness |
| `/signals` | Authenticated | Live Signals / Signal History | Signals | Review current or historical system signals | Filter, inspect, export | `/signals/*` | Working | Live, history, analytics, journal and market board overlap | No valid signal with reason, stale, partial and denied | Flagship redesign with canonical SignalDetail |
| `/signal-journal` | Basic+ | Signal Journal | Signals | Review signal reasoning and outcome | Filter/review signal history | `/signals/journal` and related data | Partial | Overlaps Signals history and Trade Journal | Missing outcomes, no-signal, historical evaluation context | Merge concepts carefully; preserve user notes vs system data |
| `/analytics` | Premium+ | Signal Analytics | Research | Analyze signal metrics | Inspect charts/export | `/signals/analytics`, exports | Working | Overlaps Performance and Model Performance metrics | Sample size, period, confidence/calibration context | Separate long-term analytics from daily reports |
| `/news` | Public/read API | News | Analysis | Read market and macro news | Filter and paginate | `/news` | Working | News is repeated in dashboard, briefing and market pages | Provider outage, stale article, empty filters | Keep shared NewsPanel and freshness metadata |
| `/ai-insights` | Authenticated; AI feature-gated API | AI Insights | AI | Request model predictions | Select asset/timeframe and inspect output | `/assets`, `/predictions` | Working | AI output is also displayed in dashboard, market pages and terminal | Model unavailable, warming-up, data quality, no prediction | Consolidate into AI Decision Inspector |
| `/model-performance` | Pro+ | Model Performance | AI | Review model outcomes | Filter/refresh performance | `/predictions/model-performance` | Working | Overlaps Analytics and proposed Calibration | Evaluation period, sample size, confidence interval, drift | Keep as model operations view; add calibration contract |
| `/heatmap` | Premium+ | Market Heatmap | Signals | Scan market breadth visually | Change metric/market | `/market-data/heatmap` | Working | Same assets and signal metrics appear in Markets and Scanner | Missing metric, partial market, stale cells | Share Heatmap domain component |
| `/risk` | Authenticated | Risk Manager | Portfolio | Calculate position/risk/reward | Calculate sizing or inspect portfolio risk | `/risk/*`, `/signals/position-analysis` | Working | Risk is also presented in Trading and signal detail | Invalid inputs, no broker, stale balance, hard limit rejection | Flagship safety flow; consolidate risk context |
| `/settings` | Authenticated | Settings | Account | Manage profile, preferences, 2FA and integrations | Update settings/security | `/auth/me`, 2FA, push, preferences | Working | Account concerns are mixed in one page; broker connections are separate | Secret preservation, verification, recovery, unavailable push | Split into Preferences, Security and Integrations |
| `/advanced-analysis` | Premium+ | Advanced Analysis | AI | Inspect technical structures and zones | Select asset/timeframe and analyze | `/assets`, OHLCV, `/market-data/advanced` | Working | Overlaps Terminal and asset detail technical views | Stale/partial calculations and no valid structure reason | Keep as expert analysis panel, reuse TechnicalContext |
| `/auto-generate` | Admin operational use | Auto Generate Signals | Signals/Admin | Operate scheduled signal generation | Start/stop/run/save config | `/signals/auto-generate/*` | Partial | Hidden admin navigation but not an admin page route; overlaps signal generation operations | Job progress, failed job, provider dependency, audit record | Move into Admin Jobs/Operations |
| `/trading` | Authenticated; broker-dependent | Trading | Portfolio | Submit and monitor paper/live orders | Review and submit order | `/trading/*`, protective orders, broker status | Working | Trading and Broker Connections are separate despite direct dependency | Buying power, max loss, order pending/rejected, confirmation | Safety-first execution workspace |
| `/broker-connections` | Premium+ | Broker Connections | Portfolio | Connect/test/disconnect brokers | Manage connection | `/trading/brokers`, connection endpoints | Working | Connection status repeated in Trading and Settings | Provider outage, credential invalid, reauth, secret redaction | Keep under Integrations; shared provider state |
| `/briefing` | Premium+ | Morning Briefing | Overview | Explain what changed since prior session | Read/refresh briefing | Heatmap, news, calendar, signals, OHLCV | Working | Overlaps dashboard and daily report concept | Data cutoff, incomplete sections, source freshness | Distinguish narrative briefing from dashboard/report |
| `/economic-calendar` | Public/read API | Economic Calendar | Analysis | Review macro events | Filter/date review | `/news/economic-calendar` | Working | Repeated in News, Briefing and Terminal module | Timezone, revised/missing event, provider outage | Shared calendar component |
| `/mtf-analysis` | Premium+ | Multi-Timeframe Analysis | AI | Compare technical conditions across timeframes | Select asset/timeframe grid | `/signals/mtf-matrix`, EMA summary | Partial | Overlaps TA Summary and Advanced Analysis | Partial timeframe data, stale cells, no agreement | Consolidate MTF data contract |
| `/performance` | Basic+ | My Performance | Portfolio | Review user trade results | Review performance | Signals performance/history and journal stats | Working | Overlaps Analytics, Reports and Journal statistics | Period/sample/currency/closed-vs-open separation | Consolidate personal performance domain |
| `/ta-summary` | Premium+ | TA Summary | AI | Review technical ratings and AI/EMA tabs | Change tab/filters | TA summary, AI summary, EMA summary | Working | Overlaps MTF, Signals and market cards | Data freshness, unavailable timeframe, no rating | Keep as compact Technical Summary component |
| `/journal` | Basic+ | Trade Journal | Portfolio | Record and review user trades | Add/edit/delete entry, tax export | `/journal/*` | Working | User journal and Signal Journal naming is confusing | Empty, validation, import/export failure | Separate user notes from system signal journal |
| `/help` | Public/authenticated shell | Help & FAQ | Account | Explain product and recovery paths | Search/read help | Static template | Partial | Help has no searchable content model or support status | Missing article, contact/support state | Improve after information architecture |
| `/asset/<asset_id>` | Authenticated API | Asset Detail | Markets | Deep dive on one asset | Switch tabs and inspect | Asset, OHLCV, indicators, sentiment, signals, DCA | Working | Duplicates market/terminal/analysis panels and has many local chart concerns | Missing asset, stale chart, partial tabs | Use as canonical asset detail target |
| `/admin` | Admin | Admin Overview | Admin | Monitor platform and recent operations | Inspect health/users/configs | `/admin/dashboard`, users, configs, audit | Working | Needs operational incident aggregation | Provider/job/model/report health | Expand into control plane |
| `/admin/users` | Admin | Users | Admin | Manage users/roles/approval | Approve/reject/edit/revoke | `/admin/users/*`, roles, sessions | Working | User/security/session actions are split across pages | Bulk actions, audit context, failure recovery | Keep, standardize admin tables |
| `/admin/logs` | Admin | System Logs | Admin | Review application logs | Filter/delete | `/admin/system-logs` | Working | Overlaps Audit Log and API config logs | Request ID, service/severity filter, retention context | Keep as operations log |
| `/admin/api-configs` | Admin | API Configurations | Admin | Manage data/provider configs | Create/update/test/pause | `/admin/api-configs/*`, providers/logs | Working | Provider health and config concepts overlap | Freshness/latency/error trend, secret state | Split config from health telemetry |
| `/admin/assets` | Admin | Assets | Admin | Manage tracked universe | Create/update/search/enable | `/assets/*`, catalog/search | Working | Asset catalog/search is also used by user pages | Bulk partial failure and audit | Keep domain, share asset contracts |
| `/admin/platform-config` | Admin | Platform Configuration | Admin | Manage feature/timeframe/market config | Update config | `/admin/platform-config` | Working | Entitlement/config values also affect every page | Preview, validation, rollback, audit | Keep as config control plane |
| `/admin/telegram-alerts` | Admin | Telegram Alerts | Admin | Operate alert channels | Add/test/broadcast/delete | `/admin/telegram/*` | Working | Notification channels overlap user Settings and Notifications | Delivery state, rate limit, audit | Keep operational view |
| `/admin/sessions` | Admin | Login Sessions | Admin | Review/revoke sessions | Revoke/delete | `/admin/sessions/*` | Working | Security page also covers security events | Empty, expired, bulk revoke confirmation | Keep, consolidate security model |
| `/admin/audit-log` | Admin | Audit Log | Admin | Review administrative activity | Filter/clear | `/admin/audit-logs` | Working | System Logs, security and user actions lack one event taxonomy | Request/correlation ID, actor/resource diff | Keep as audit trail foundation |
| `/admin/security` | Admin | Security | Admin | Review security status/events | Inspect status/actions | `/admin/telegram/security-test` and security data | Partial | Overlaps sessions and audit log | Event source, severity, remediation, historical timeline | Expand after security event contract |

## API Contract Map

All API paths are registered under `/api/v1`. The endpoint counts below were extracted from route decorators. Callers include Jinja page scripts, standalone page controllers, the Terminal SPA and background/admin workflows.

| API domain | Count | Representative endpoints | Primary UI consumers | Contract/UX concern |
|---|---:|---|---|---|
| Auth | 18 | `/auth/login`, `/auth/me`, `/auth/2fa/*`, `/auth/push/*` | Login, register, settings, both shells | Two shells own auth state separately; standardize session-expiry and entitlement response |
| Signals | 29 | `/signals`, `/signals/summary`, `/signals/history`, `/signals/analytics`, `/signals/generate`, exports | Dashboard, Signals, Scanner, Terminal, AI/briefing | Many overlapping response shapes and lifecycle states; define canonical Signal/SignalDetail |
| Assets | 12 | `/assets`, `/assets/search`, `/assets/<id>/ticker`, `/assets/ask` | Asset selector, Markets, admin, Terminal | Shared asset search/selector is not yet a component contract |
| Market data | 10 | OHLCV, indicators, sentiment, TA/EMA/AI summaries, heatmap, advanced | Most analytical pages | Freshness and partial-data metadata are not uniform |
| Portfolio | 5 | list, add, update, delete, CSV export | Portfolio, performance | Currency and realized/unrealized semantics need shared labels |
| Watchlist | 6 | lists, items, context | Watchlist, scanners, dashboard | Multiple consumers and different empty-state behavior |
| Backtesting | 4 | list, run, walk-forward, detail | Backtesting, Terminal | Two backtest engines and schemas must remain explicit |
| News | 2 | news list, economic calendar | News, Briefing, Markets, Terminal | Date/timezone and provider freshness need shared metadata |
| Scanner | 14 | filters, run, Delta MTF/bubbles/screeners, saved screens | Scanner, Delta Scanner, Delta Bubbles | Specialized engines share filter/result concepts but not one contract |
| Admin | 50 | dashboard, users, configs, sessions, audit, brokers, logs | Admin pages and hidden operations | Needs operations taxonomy for jobs/providers/models/reports |
| Notifications | 3 | list, mark read, mark all read | Shared top bar and Terminal | Notification categories/severity/deep links are not one documented contract |
| Predictions | 2 | asset prediction, model performance | AI Insights, Model Performance | Prediction vs calibration vs historical validation must be distinct |
| Risk | 3 | position size, risk/reward, portfolio risk | Risk, Trading, Signal detail | Server-side hard limits and context should be visible before execution |
| Journal | 8 | entries, stats, tax report/export | Trade Journal, Performance | User-generated notes and derived/system data need visual separation |
| Trading | 13 | broker status/connections, balances, positions, orders | Trading, Broker Connections, Terminal | Paper/live mode, order intent, broker response and confirmation need one flow |
| Protective orders | 4 | list/create/update/delete | Trading and background tasks | Order lifecycle and failure states should be visible in execution UI |
| Comparison | 1 | comparison read | Asset/market comparison | Minimal contract; likely useful for reports and asset detail |
| System | 2 | `/system/health`, `/system/ready` | Deployment/ops checks | Not yet represented as a user-facing status model |
| Geopolitical risk | 1 | risk overview | Markets/Terminal | Specialized data needs freshness/caveat state |
| Forex | 1 | forex overview | Markets/Terminal | Provider and valuation context should use shared MarketHeader |
| Sentiment | 1 | fear/greed | Markets/Terminal | Sentiment should not be visually treated as a prediction |
| Put/call ratio | 1 | options ratio | Markets/Terminal | Source timestamp and unavailable state need standardization |
| Dhan | 4 | status, indices, expiries, chain | Dhan page | Provider-specific but now has input boundaries; align with option data component |
| Public config | 1 | site config | Landing/public shell | Public data must remain separate from authenticated entitlements |

## Reusable Component and State Map

### Existing dashboard reuse points

| Area | Existing implementation | Current issue | UI-2 target |
|---|---|---|---|
| Shell | `frontend/templates/partials/base.html` | Large shared shell with page-local overrides and mixed inline styles | `AppShell`, grouped nav, top bar, context bar and responsive primitives |
| Shared client | `frontend/static/js/app.js` | Owns API, auth bootstrap, theme, notifications, ticker and sidebar concerns | Split stable services from UI state and define lifecycle cleanup |
| Shared API | `frontend/static/js/app.js` API object | Vanilla client has no typed contract layer or request cancellation standard | Add small compatibility helpers and domain normalizers, not a framework rewrite |
| Styles | `frontend/static/css/main.css` plus page `<style>` blocks | Tokens and component patterns are duplicated; density varies page to page | Consolidate tokens, states, controls, tables, cards and breakpoints |
| Charts | Chart.js vendor plus Lightweight Charts on selected pages | Multiple chart lifecycles and fallback patterns | Shared chart wrapper with explicit empty/stale/error states |
| Loading/empty/error | Per-page skeletons and messages | Inconsistent copy and state coverage | `LoadingState`, `EmptyState`, `ErrorState`, `StaleState`, `PermissionState` |
| Asset selection | Repeated selects/search/asset list logic | Different labels, limits and URL/state behavior | `AssetSelector` and normalized Asset contract |
| Filters | Repeated market/timeframe/date/filter controls | Permanent toolbars become crowded and semantics drift | `FilterBar`, drawer, chips, URL-safe state |
| Signal presentation | Repeated signal cards/tables/panels | Direction/confidence/evidence/quality context is inconsistent | `SignalSummary`, `SignalDetail`, `EvidencePanel`, `DataQualityBadge` |
| Admin tables | Page-local tables and action handlers | Similar pagination, confirm and mutation behavior | `AdminTable`, mutation guard, audit context |

### Existing terminal reuse points

`frontend-Terminal` already provides a separate router, state store, API client and components for headers, navigation, async sections, signal cards, stat cards, login gates and page headers. It also has real modules for terminal, trading logs, backtest, portfolio, watchlist, scanner, news, charts, predictions, risk, alerts, economic calendar, admin, geopolitical risk, forex, sentiment and put/call ratio.

The registry also contains stub modules for macro dashboard, confluence engine, regime matrix, US economic data, GDP/growth, inflation, labour market, Federal Reserve, banking/liquidity, yield curve, global central banks, socioeconomic data, asset pages, educational insights and reports. These are product hypotheses, not implemented functionality.

## Duplication and Fragmentation Findings

| Finding | Evidence | Impact | Proposed direction |
|---|---|---|---|
| Two production-capable frontend architectures | Jinja dashboard plus `/terminal` SPA | Duplicate navigation, auth, API clients, states and styling | Keep both temporarily; align contracts/tokens first, then choose canonical long-term shell |
| Three terminal-like experiences | `/markets/terminal`, `/terminal`, and Advanced Analysis | Users cannot predict where deep analysis belongs | Define Terminal as workspace and asset detail as canonical deep link; de-emphasize duplicate entry points |
| Signal concepts are fragmented | Signals, history, journal, scanner, auto-generate, market board, performance | No single lifecycle or explanation mental model | Build canonical SignalSummary/SignalDetail and route aliases |
| Performance concepts are fragmented | Performance, Analytics, Model Performance, Journal stats, backtest results | Metrics can appear comparable when scopes differ | Label data source, sample, evaluation period and closed/open status everywhere |
| Market/technical views are fragmented | Markets, asset detail, TA Summary, MTF, Advanced Analysis, Heatmap | Repeated selectors and charts | Shared MarketHeader, AssetSelector, TimeframeSelector and TechnicalContext |
| Operational views are incomplete | Admin config/logs/security/sessions without a Jobs/Incidents/Provider Health view | Operators cannot see one system status | Add UI only for existing data; mark missing telemetry as backend data required |
| Missing Reports route | No `/reports` page route or report blueprint | Date-wise review cannot be implemented honestly yet | UI-0 records a data gap; UI-7 needs backend contract before rich report UI |
| Missing AI Inspector route | AI output is distributed across cards/pages | Users cannot inspect evidence progressively | UI-9 should use existing prediction/signal fields and mark absent fields explicitly |
| Missing calibration/drift contract | Model performance is present, calibration/drift are not | Risk of implying reliability from raw performance | UI-11 must not invent metrics; require backend data |
| Missing `/new1` and `/new2` sources | Routes exist, directories do not | Link can fail at runtime | Remove stale registrations or restore source before deployment |

## Data and Capability Gap Register

These are gaps identified from actual routes/models/API payload usage. They are not fabricated frontend fields.

| Gap ID | `BACKEND DATA REQUIRED` | Needed by | Why it matters | Fallback until available | Priority |
|---|---|---|---|---|---|
| DATA-01 | `report.id`, `report.type`, `report.period_start`, `report.period_end`, `report.status`, `report.generated_at`, `report.data_cutoff`, `report.completeness` | Reports Home and Daily Report | Authoritative date-wise reporting and auditability | Explain that Reports are not available; link to Analytics/exports | P0 |
| DATA-02 | Report filters: market, asset, timeframe, signal type, confidence range, model, regime, status | Reports filtering/comparison | Reproducible report views | Show only filters supported by existing endpoints | P0 |
| DATA-03 | `signal.no_signal_reason`, state transitions and invalidation metadata | Signals and AI Inspector | Empty signal states must explain only what the system knows | `NO VALID SIGNAL` with generic insufficient-data copy only when supplied by backend | P0 |
| DATA-04 | Calibrated confidence, calibration window, sample size and interval | AI Inspector, Model Performance, Reports | Prevent raw probability from looking like accuracy | Show `Not evaluated` and raw model output only when labeled | P0 |
| DATA-05 | Model registry/version, feature/data version and drift status | AI/admin quality | Auditability and model operations | Show stored model version where available; omit unsupported claims | P1 |
| DATA-06 | Provider freshness, latency, error rate, circuit state and feed timestamp | Shell, dashboard, admin provider view | Users need to know whether data is usable now | Existing data-quality/stale labels; no guessed latency | P0 |
| DATA-07 | Job/report generation state, retries, dependencies and duration | Admin Jobs and Reports Operations | Operators need recovery actions | Existing logs/audit only; no fake job cards | P1 |
| DATA-08 | User display timezone preference and authoritative timestamp timezone | Global date/time and reports | Prevent date boundary mistakes | Explicit UTC/local labels based on actual metadata | P0 |
| DATA-09 | Portfolio currency policy, realized/unrealized and broker buying power | Portfolio/Trading/Risk | Capital and maximum-loss decisions need correct scope | Show unavailable/unknown rather than combine currencies | P0 |
| DATA-10 | Signal evidence/counter-evidence schema with source and timestamp | Signal Detail/AI Inspector | Progressive disclosure without invented explanations | Render existing reasoning fields only | P0 |
| DATA-11 | Product analytics events and funnel definitions | Admin/product operations | Measure activation and workflow outcomes | No fabricated usage metrics | P2 |

## State and Accessibility Baseline

Observed strengths:

- Shared skip link, sidebar labels, focus-visible rules and tier overlays exist in the primary shell.
- Recent work removed inline handlers and added stale-request/duplicate-mutation guards on multiple high-risk pages.
- The Terminal has a separate login gate, session-expiry event and keyboard-capable navigation primitives.

Observed risks:

- State copy and semantics differ by page; loading/error/empty/stale/partial/no-signal/permission states are not one reusable system.
- Color, badges and compact tables carry significant meaning; the UI-2 audit must verify non-color labels and contrast.
- `href="#"` is still used for action-like links and generated pagination, so click prevention and keyboard semantics need a complete audit.
- Date/time rendering is distributed across browser-local and page-specific formatting; a timezone policy is not yet a shared preference contract.
- No repository-wide frontend accessibility, browser E2E or visual-regression gate is present.

## Performance Baseline

Observed risks to measure before optimization:

- Page-local scripts independently fetch signals, heatmaps, summaries, news and tickers; duplicate calls are possible across shell/widgets.
- Many pages render dynamic HTML strings and charts locally; payload bounds and stale-request guards are inconsistent outside recently hardened pages.
- Dashboard and terminal load separate CSS, API and component implementations.
- Chart.js and Lightweight Charts are both used; chart lifecycle, lazy loading and bundle cost need measured budgets.
- The primary shell loads shared scripts on every Jinja page, while page-specific scripts are mixed between external files and inline blocks.

Performance evidence needed in UI-17:

- Page/API request waterfall and duplicate-call count.
- P50/P95/P99 for page load, signals, market data, scanner, backtest start and terminal bootstrap.
- Payload sizes for charts, tables and exports.
- Browser memory and chart cleanup under navigation/repeated refresh.
- CSS/JS bundle and third-party asset cost.

## UI-0 Decisions and Next Phase

1. Do not rebuild the product or introduce a new frontend framework in UI-0.
2. Treat the Flask/Jinja surface as the current canonical product while preserving `/terminal` as an advanced workspace.
3. Do not expose `/new1` or `/new2` until their missing source directories are resolved.
4. Start UI-1 with workflow-based information architecture: Overview, Markets, Signals & Discovery, AI & Analysis, Research, Portfolio, Account and Admin.
5. Start UI-2 by consolidating tokens and reusable states before changing every page.
6. Treat Reports, AI Inspector, calibration, provider operations and job operations as staged capabilities with explicit backend-data requirements.
7. Keep user and system data visually distinct; never turn missing data into a confident-looking metric.
8. Use one logical phase per checkpoint and retain the existing API contracts.

**Recommended next phase:** UI-1 - information architecture and global navigation model.  
**Implementation boundary:** UI-1 may change navigation labels/grouping and shared shell presentation, but must not delete routes or invent missing report/AI data.  
**Multi-agent decision:** do not parallelize UI-1/UI-2 yet. Shared shell and token work touches common files and parallel edits would increase merge and regression risk; a separate agent could be considered later for an isolated read-only accessibility audit after explicit approval.
