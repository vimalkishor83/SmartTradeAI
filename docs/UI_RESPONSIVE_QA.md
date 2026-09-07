# SmartTrade AI Responsive UI QA

## Scope

This pass covers the page templates under `frontend/templates` and the shared
authenticated shell. It is presentation-only. No Python, route, API, database,
authentication, WebSocket, scheduler, or business logic files were changed.

The template inventory contains 59 page templates plus the shared base partial.
The route inventory expands that to 62 URL contexts because market slugs,
signal history, and asset detail are dynamic variants of shared templates.

## Viewport Contract

| Viewport group | Required sizes | Responsive contract checked |
| --- | --- | --- |
| Desktop | 1920x1080, 1600x900, 1366x768 | Content uses the available main-wrapper width; cards and columns do not reserve an artificial right-side gap. |
| Tablet | 1024x768, 820x1180, 768x1024 | Sidebar/content transition, readable KPI grids, wrapping toolbars, and fluid charts. |
| Mobile | 430x932, 390x844, 360x800 | No page-level horizontal overflow; tables scroll inside their wrappers; controls and card headers wrap cleanly. |

## Page-by-Page Coverage

Status in this table means static responsive contract verification from the
template and CSS source. The live browser control was not available in this
session, so a screenshot-level visual sign-off remains outstanding.

### Public and Authentication

| Page or route | Template | Status | Notes |
| --- | --- | --- | --- |
| Home | `landing.html` | Static pass | Existing desktop, tablet, and mobile sections retained; live signal snapshot now scrolls inside its card on narrow screens. |
| Login | `auth/login.html` | Static pass | Shared auth controls and 900px single-column breakpoint retained. |
| Register | `auth/register.html` | Static pass | Shared auth controls and 900px single-column breakpoint retained. |
| Forgot password | `auth/forgot_password.html` | Static pass | Shared auth controls and small-screen form behavior retained. |
| Reset password | `auth/reset_password.html` | Static pass | Shared centered auth card remains fluid. |
| Verify email | `auth/verify_email.html` | Static pass | Shared centered auth card remains fluid. |

### Legal and Markets

| Page or route | Template | Status | Notes |
| --- | --- | --- | --- |
| Legal index | `legal/index.html` | Static pass | Existing three-column to one-column card grid and legal imagery retained. |
| Terms | `legal/terms.html` | Static pass | Shared legal navigation and long-content wrapping. |
| Privacy | `legal/privacy.html` | Static pass | Shared legal navigation and long-content wrapping. |
| Disclaimer | `legal/disclaimer.html` | Static pass | Shared legal navigation and long-content wrapping. |
| Risk disclosure | `legal/risk_disclosure.html` | Static pass | Shared legal navigation and long-content wrapping. |
| Cookie policy | `legal/cookie_policy.html` | Static pass | Shared legal navigation and long-content wrapping. |
| Acceptable use | `legal/acceptable_use.html` | Static pass | Shared legal navigation and long-content wrapping. |
| Refund policy | `legal/refund_policy.html` | Static pass | Shared legal navigation and long-content wrapping. |
| Crypto, Forex, Commodities, Indian Stocks, Indices | `markets/index.html` | Static pass | Shared table scrolling and chart max-width rules. |
| Commodities legacy template | `markets/commodities.html` | Static pass | Existing standalone market presentation retained. |
| Market terminal | `markets/terminal.html` | Static pass | Existing tab wrapping and search max-width rules retained. |
| Asset detail | `asset/detail.html` | Static pass | Existing chart flex chain retained; shared tables and canvases cannot escape cards. |

### Authenticated Modules

| Page or route | Template | Status | Notes |
| --- | --- | --- | --- |
| Dashboard | `dashboard/index.html` | Static pass | Shared cards, KPI grid, charts, and tables. |
| Dhan indices and options | `dashboard/dhan_indices.html` | Static pass | Option-chain table scrolls within its card; header controls wrap. |
| Scanner | `dashboard/scanner.html` | Static pass | Filter controls and table wrapper use shared mobile rules. |
| Delta scanner | `dashboard/delta_scanner.html` | Static pass | Multiple table wrappers remain independently scrollable. |
| Delta bubbles | `dashboard/delta_bubbles.html` | Static pass | Bubble canvas keeps its own scroll area; table wrapper is bounded. |
| Backtesting | `dashboard/backtesting.html` | Static pass | Chart canvas and result table remain bounded. |
| Portfolio | `dashboard/portfolio.html` | Static pass | Portfolio table remains internally scrollable. |
| Watchlist | `dashboard/watchlist.html` | Static pass | Shared cards and responsive columns. |
| Signals and signal history | `dashboard/signals.html` | Static pass | Filter bars stack on narrow screens; data tables scroll. |
| Analytics | `dashboard/analytics.html` | Static pass | Context bar, charts, KPI cards, and tables are fluid. |
| Reports | `dashboard/reports.html` | Static pass | Report KPI grid, chart wrapper, and tables are fluid. |
| Market news | `dashboard/news.html` | Static pass | Filter control and news table are bounded. |
| AI Insights | `dashboard/ai_insights.html` | Redesigned and verified statically | Prediction desk header, control/model cards, empty/loading/locked states, confluence summary, and result cards share a fluid layout; two columns above 1100px and one column at or below 1100px. |
| Model performance | `dashboard/model_performance.html` | Static pass | Trend canvas, table, search, and data columns are bounded. |
| Market heatmap | `dashboard/heatmap.html` | Static pass | Existing auto-fill tile grid retained. |
| Risk manager | `dashboard/risk.html` | Changed and verified statically | Legacy four-column inline KPI declaration is overridden to two readable columns at tablet/phone sizes. |
| Account settings | `dashboard/settings.html` | Changed and verified statically | Backup codes change to two columns on narrow phones; tables and 2FA layout stay bounded. |
| Advanced analysis | `dashboard/advanced_analysis.html` | Static pass | Existing chart and toolbar breakpoints retained; shared canvas bounds added and Fibonacci output is bounded inside a scroll wrapper. |
| Auto generate | `dashboard/auto_generate.html` | Static pass | KPI grid and table wrappers use shared responsive rules. |
| Trading | `dashboard/trading.html` | Static pass | Broker form and order tables remain fluid. |
| Algo trading | `dashboard/algo_trading.html` | Static pass | Shared card columns and context/status presentation retained. |
| Broker connections | `dashboard/broker_connections.html` | Static pass | Connection table scrolls within its card. |
| Morning briefing | `dashboard/briefing.html` | Static pass | Context bar, chart canvases, and tables are bounded. |
| Economic calendar | `dashboard/economic_calendar.html` | Static pass | Filter controls wrap on small screens. |
| MTF analysis | `dashboard/mtf_analysis.html` | Static pass | Intentionally wide matrix scrolls inside the table wrapper. |
| Performance | `dashboard/performance.html` | Changed and verified statically | Six-column hour heatmap changes to three columns on narrow phones. |
| TA summary | `dashboard/ta_summary.html` | Static pass | Intentionally wide rating tables scroll inside wrappers. |
| Trade journal | `dashboard/journal.html` | Static pass | Filter controls and journal tables remain bounded. |
| Signal journal | `dashboard/signal_journal.html` | Static pass | Filter/search controls stack on narrow screens. |
| Help and FAQ | `dashboard/help.html` | Static pass | Shared cards and prose wrapping. |

### Admin

| Page or route | Template | Status | Notes |
| --- | --- | --- | --- |
| Admin dashboard | `admin/index.html` | Static pass | KPI cards and tables use shared responsive rules. |
| Users | `admin/users.html` | Static pass | Search/actions wrap; tables scroll. |
| System logs | `admin/logs.html` | Static pass | Log table is internally scrollable. |
| API configurations | `admin/api_configs.html` | Static pass | Existing configuration panel breakpoints retained; connection logs scroll inside the modal on narrow screens. |
| Assets | `admin/assets.html` | Static pass | Search, filters, table, and result panel are bounded. |
| Platform configuration | `admin/platform_config.html` | Static pass | Shared cards and forms remain fluid. |
| Telegram alerts | `admin/telegram_alerts.html` | Static pass | Channel table and controls remain bounded. |
| Sessions | `admin/sessions.html` | Static pass | Session table scrolls inside its card. |
| Audit log | `admin/audit_log.html` | Static pass | Filter and audit table remain bounded. |
| Security | `admin/security.html` | Static pass | Shared cards and forms remain fluid. |
| Daily compound calculator | `admin/daily_compound_calculator.html` | Changed and verified statically | Phone layout now wraps top bar/actions, stacks paired inputs, scrolls tabs, and wraps action buttons. |

## Files Changed In This Pass

- `frontend/static/css/main.css`
  - Added shared min-width rules for flex/grid children.
  - Added bounded table and canvas behavior.
  - Added mobile toolbar, header, notification, context-bar, KPI, and heatmap rules.
  - Added the AI Insights fluid layout.
- `frontend/templates/dashboard/ai_insights.html`
  - Added a page-specific prediction desk header, visual hierarchy, responsive empty/locked/loading states, confluence KPI cards, and readable prediction result cards.
  - Preserved all existing API calls, IDs, controls, accessibility relationships, and prediction rendering behavior.
- `frontend/templates/admin/daily_compound_calculator.html`
  - Added phone-only layout rules.
- `frontend/templates/landing.html`
  - Bounded the live signal snapshot table inside a touch-scroll wrapper.
- `frontend/templates/dashboard/advanced_analysis.html`
  - Bounded dynamically rendered Fibonacci levels inside a table wrapper.
- `frontend/templates/admin/api_configs.html`
  - Bounded dynamically rendered connection logs inside the modal.

## Verification

- `122 passed` across the focused UI/template/accessibility contract suite.
- `git diff --check` passed.
- Template block balance and responsive selector checks passed, with one
  harmless static script-count false positive from an asset-detail script
  containing a literal closing-tag string.
- Backend changes: **NONE**.
- Git push: not performed in this pass.
- Production deployment: not performed in this pass.

## Outstanding

1. Run the actual screenshot-level browser QA at all nine requested viewport
   sizes, including authenticated and super-admin sessions.
2. Check interaction states visually: sidebar open/collapsed, command palette,
   notification menu, table scroll affordance, filter wrapping, loading,
   empty, error, and populated states.
3. Production still serves the older AI Insights markup; deploy this local page
   only after browser pass and an explicit user request for production synchronization.
