import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { statCardHtml } from "../components/statCard.js";
import { renderAsync } from "../components/asyncSection.js";

export function renderBacktest(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="backtest-results" class="grid grid-cards"></div>
  `;

  renderAsync(
    main.querySelector("#backtest-results"),
    () => api.get("/backtesting"),
    (data) => {
      const runs = data.results || data.items || data || [];
      if (!runs.length) return `<div class="card text-3">No backtest runs yet. Trigger one from the Backtest Lab in the main app.</div>`;
      return runs.map((r) => `
        <div class="card">
          <div style="font-weight:700;">${r.strategy || r.name || "Backtest run"}</div>
          <div class="text-3" style="font-size:11px; margin-bottom:8px;">${r.symbol || r.asset_symbol || ""} · ${r.period || ""}</div>
          ${statCardHtml({ label: "Win rate", value: r.win_rate !== undefined ? `${Math.round(r.win_rate)}%` : "—", tone: "up" })}
        </div>
      `).join("");
    },
  );
}
