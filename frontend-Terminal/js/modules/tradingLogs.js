import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";
import { emptyStateHtml } from "../components/emptyState.js";

export function renderTradingLogs(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="journal-table" class="card"></div>
  `;

  renderAsync(
    main.querySelector("#journal-table"),
    () => api.get("/journal"),
    (data) => {
      const entries = data.entries || data.items || data || [];
      if (!entries.length) return emptyStateHtml("No journalled trades yet — every paper trade you take will show up here.", "\u{1F4D2}");
      const rows = entries.map((e) => `
        <tr>
          <td>${e.date || e.created_at || "—"}</td>
          <td>${e.symbol || e.asset_symbol || "—"}</td>
          <td>${(e.direction || e.side || "").toUpperCase() || "—"}</td>
          <td class="mono">${e.pnl ?? "—"}</td>
          <td class="text-2">${e.notes || ""}</td>
        </tr>
      `).join("");
      return `
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>Date</th><th>Symbol</th><th>Side</th><th>P&L</th><th>Notes</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      `;
    },
  );
}
