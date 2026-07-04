# Prompt: Generate Static Demo/Mockup Pages with Dummy Data

A prompt for generating standalone HTML mockups of every page in this app, fully
populated with realistic fake data, disconnected from the live backend/database.
Useful for demos, screenshots, pitch decks, or showcasing the product's UI without a
running server, real API keys, or seeded data. Works with any coding agent (Claude
Code, GitHub Copilot, Codex, Cursor, etc.).

---

## Prompt to paste

```
Create static demo/mockup versions of every page listed below, populated with
realistic dummy data, completely disconnected from the live backend, database, and
APIs. Do not modify any live/production source files, backend code, or the database —
only create new files. You decide the output format, folder structure, and how to
strip out live data/wiring — use your own judgment on implementation.

This is a trading-signals / market-analytics platform. Below are all pages/modules,
grouped by section, with what each one needs to show.

## Auth
- Login — email/password form, "forgot password" link, sign-up link
- Register — sign-up form (name, email, password, confirm)

## Landing
- Landing / marketing page — hero section, feature highlights, pricing or CTA,
  no live data needed

## Overview
- Dashboard (home) — greeting header; KPI cards for win rate, active signals
  (buy/sell split), average confidence, open P&L; a live signals table (asset, market,
  timeframe, signal type, entry price, confidence + SL/target levels, risk:reward,
  time); a signal-mix donut chart (buy/sell/hold/exit); a win-rate-by-market bar
  chart; a market sentiment gauge; a market heatmap grid (symbol, % change, price);
  an open-P&L ticker strip
- Morning Briefing — market status badges (open/closed per market), top movers list
  (gainers/losers with price + % change), signal mini-cards, economic events summary

## Markets (5 pages, same layout pattern, different asset sets)
- Crypto, Forex, Commodities, Indian Stocks, Indices — each shows: a grid of asset
  cards (symbol, name, exchange tag, price, % change, "Generate Signal" button); a
  market sentiment panel (score, bull/bear split, RSI/MACD/trend/volume mini-stats);
  a signals table for that market (asset, signal type, entry, SL, T1/T2/T3, R:R,
  confidence, time, action)

## Signals & Tools
- All Signals — KPI row (win rate, active signals, avg confidence, top signal);
  an open-positions/live-P&L table (asset, timeframe, type, entry, current price,
  P&L%, distance to SL/target, age); filters (market, timeframe, signal type,
  min-confidence slider); tabs for Live Signals vs Signal History; a results table
- Auto Generate — status panel (on/off), asset + timeframe selection checklist,
  interval setting, start/stop controls, live run log
- Scanner — filter form (market, indicators/conditions to scan for), run button,
  results table of matching assets
- Market Heatmap — grid of tiles per asset (symbol, % change color-coded, price),
  market filter dropdown, normal/percentage view toggle
- Backtesting — strategy/asset/timeframe/date-range selection form, run button,
  results: equity curve chart, win rate, total trades, profit factor, max drawdown,
  trade-by-trade table
- AI Insights — AI-generated market commentary/predictions per asset, confidence
  scores, model version info

## Analysis
- TA Summary — table of assets x timeframes with technical-rating cells (strong
  buy/buy/neutral/sell/strong sell), color-coded
- MTF Analysis — multi-timeframe confluence table per asset, summary KPI cards
  (bullish/bearish/neutral counts)
- Model Performance — accuracy/precision/recall stats per model, performance-over-time
  chart, per-market breakdown table
- Advanced Analysis — larger candlestick price chart with overlays (support/resistance
  lines, Fibonacci levels), liquidity pool table, timeframe tabs
- Analytics — win-rate-by-market bar chart, signal-type distribution donut chart,
  performance-by-timeframe table
- Market News — card grid of news headlines (source, timestamp, summary, "read more"
  link), sentiment/impact tags
- Economic Calendar — table of scheduled economic events (date/time, country, event
  name, impact level high/medium/low, forecast/previous/actual values)

## Portfolio
- Portfolio — KPI cards (total invested, current value, total P&L, P&L %); holdings
  table (asset, qty, buy price, current price, invested, current value, P&L, P&L%,
  days held, action); "Add Position" and "Download CSV" actions
- Trading — account balance summary, open positions table, order placement form
  (symbol, side, quantity, order type), order history table
- Watchlist — list of saved assets with live price, % change, confluence/signal badge,
  remove action
- Risk Manager — position-size calculator (account size, risk %, entry, stop loss ->
  computed position size), risk:reward calculator, buy/sell direction toggle
- My Performance — equity curve chart, win rate, avg win/loss, profit factor, best/
  worst trade stats
- Trade Journal — list/table of past trades with notes, outcome (win/loss), P&L,
  screenshots/tags if applicable; an empty state variant with no trades yet

## Admin
- Admin Panel (index) — summary stats (total users, active signals, system health)
- Users — user management table (id, username, email, role, plan, status, last
  login, joined date, actions)
- API Configs — list of connected exchange/data-provider API configs (name, status,
  masked key), add/edit modal
- Assets — manage tradable assets table (symbol, name, market, exchange, active
  toggle, actions)
- System Logs — table of log entries (level, module, message, timestamp), level
  filter

## Account
- Settings — profile form (name, phone, theme), notification preferences (email/
  Telegram toggles), change-password form, 2FA status, asset-selection checklist for
  which assets appear in TA Summary/MTF Analysis
- Help / FAQ — searchable FAQ list or accordion, contact/support info

## Asset Detail (dynamic page, one per asset)
- Header: symbol, market tag, name/exchange, live price + % change
- Tabs: Chart (candlestick + volume, timeframe buttons 1m/5m/15m/30m/1h/4h/1d),
  Indicators (moving averages, momentum, trend, volatility indicator values),
  Signals History (table of past signals for this asset)
- Side panel: market sentiment gauge, AI prediction CTA, quick stats (market,
  exchange, data source, status)

---

For every page above: reuse this app's real existing markup, CSS classes, and design
system so the mockup looks identical to the real product. Populate every data-driven
element with varied, realistic-looking values (not "Lorem ipsum" or "Sample 1") —
mixed positive/negative results, plausible names/prices/timestamps, believable chart
data. Preserve dark/light theme support if the app has it. When finished, report a
summary of everything created.
```
