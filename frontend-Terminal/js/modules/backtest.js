import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { statCardHtml } from "../components/statCard.js";
import { renderAsync } from "../components/asyncSection.js";
import { emptyStateHtml } from "../components/emptyState.js";

export function renderBacktest(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="backtest-results" class="grid grid-cards"></div>
  `;

  renderAsync(
    main.querySelector("#backtest-results"),
    () => api.get("/backtesting"),
    (data) => {
      // Field names confirmed against the live GET /api/v1/backtesting
      // response: top-level key is `backtests` (not "results"), and each
      // run has `asset`, `strategy`, `timeframe`, `net_profit_pct` — no
      // "period"/"name"/"symbol" fields exist.
      const runs = data.backtests || [];
      if (!runs.length) return `<div class="card">${emptyStateHtml("No backtest runs yet. Trigger one from the Backtest Lab in the main app.", "\u{1F9EA}")}</div>`;
      return runs.map((r) => `
        <div class="card card-hover">
          <div style="font-weight:700;">${r.strategy || "Backtest run"}</div>
          <div class="text-3" style="font-size:11px; margin-bottom:8px;">${r.asset || ""} · ${r.timeframe || ""} · ${r.total_trades ?? 0} trades</div>
          <div class="stat-row" style="margin-bottom:0;">
            ${statCardHtml({ label: "Win rate", value: r.win_rate !== undefined ? `${r.win_rate}%` : "—", tone: "up" })}
            ${statCardHtml({ label: "Net P&L", value: r.net_profit_pct !== undefined ? `${r.net_profit_pct}%` : "—", tone: (r.net_profit_pct || 0) >= 0 ? "up" : "down" })}
          </div>
        </div>
      `).join("");
    },
  );
}
