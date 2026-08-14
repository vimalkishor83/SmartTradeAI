import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { signalCardHtml } from "../components/signalCard.js";
import { statCardHtml } from "../components/statCard.js";
import { renderAsync } from "../components/asyncSection.js";
import { emptyStateHtml } from "../components/emptyState.js";

export function renderTerminal(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="terminal-stats" class="stat-row"></div>
    <div id="terminal-signals" class="grid grid-cards"></div>
  `;

  const signalsEl = main.querySelector("#terminal-signals");
  const statsEl = main.querySelector("#terminal-stats");
  statsEl.innerHTML = `<div class="card state-block state-loading"><span class="state-icon">\u{23F3}</span><span>Loading…</span></div>`;
  signalsEl.innerHTML = `<div class="card state-block state-loading"><span class="state-icon">\u{23F3}</span><span>Loading…</span></div>`;

  // Both stat cards and the signal grid derive from GET /signals (which
  // has `total` + per-signal confidence_score) plus GET /signals/performance
  // (whose real shape is {overall: {win_rate, total_pnl_pct, ...}, ...} —
  // NOT the flat {open_count, avg_confidence, open_pnl} originally assumed,
  // which is why every stat card showed "—" before this fix.
  Promise.all([
    api.get("/signals?status=active"),
    api.get("/signals/performance").catch(() => null),
  ]).then(([signalsData, perf]) => {
    const signals = signalsData.signals || [];
    const avgConfidence = signals.length
      ? signals.reduce((sum, s) => sum + (s.confidence_score || 0), 0) / signals.length
      : null;
    const overall = perf?.overall;

    statsEl.innerHTML = [
      statCardHtml({ label: "Open signals", value: signalsData.total ?? signals.length ?? "—" }),
      statCardHtml({ label: "Win rate (closed)", value: overall?.win_rate !== undefined ? `${overall.win_rate.toFixed(1)}%` : "—", tone: "up" }),
      statCardHtml({ label: "Avg confidence", value: avgConfidence !== null ? `${Math.round(avgConfidence)}%` : "—" }),
      statCardHtml({ label: "Total P&L (closed)", value: overall?.total_pnl_pct !== undefined ? `${overall.total_pnl_pct}%` : "—", tone: (overall?.total_pnl_pct || 0) >= 0 ? "up" : "down" }),
    ].join("");

    signalsEl.innerHTML = signals.length
      ? signals.map(signalCardHtml).join("")
      : `<div class="card">${emptyStateHtml("No active signals yet — check back after the next engine run.")}</div>`;
  }).catch((err) => {
    statsEl.innerHTML = `<div class="card">${emptyStateHtml("Couldn't load signal stats.")}</div>`;
    signalsEl.innerHTML = `<div class="card">${emptyStateHtml(err?.message || "Couldn't load signals.")}</div>`;
  });
}
