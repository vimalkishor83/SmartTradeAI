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

  renderAsync(
    main.querySelector("#terminal-stats"),
    () => api.get("/signals/performance"),
    (perf) => [
      statCardHtml({ label: "Open signals", value: perf.open_count ?? "—" }),
      statCardHtml({ label: "Win rate", value: perf.win_rate !== undefined ? `${Math.round(perf.win_rate)}%` : "—", tone: "up" }),
      statCardHtml({ label: "Avg confidence", value: perf.avg_confidence !== undefined ? `${Math.round(perf.avg_confidence)}%` : "—" }),
      statCardHtml({ label: "Open P&L", value: perf.open_pnl !== undefined ? perf.open_pnl : "—", tone: (perf.open_pnl || 0) >= 0 ? "up" : "down" }),
    ].join(""),
  );

  renderAsync(
    main.querySelector("#terminal-signals"),
    () => api.get("/signals"),
    (data) => {
      const signals = data.signals || data.items || data || [];
      if (!signals.length) return `<div class="card">${emptyStateHtml("No active signals yet — check back after the next engine run.")}</div>`;
      return signals.map(signalCardHtml).join("");
    },
  );
}
