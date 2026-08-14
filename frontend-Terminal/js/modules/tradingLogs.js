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
      // Field names confirmed against the live GET /api/v1/journal response:
      // trade_date, direction, pnl_pct/pnl_amount, asset_symbol (often null,
      // so market is shown as a fallback label) — not "date"/"symbol"/"side"/"pnl".
      const entries = data.entries || [];
      if (!entries.length) return emptyStateHtml("No journalled trades yet — every paper trade you take will show up here.", "\u{1F4D2}");
      const rows = entries.map((e) => `
        <tr>
          <td>${e.trade_date || e.created_at || "—"}</td>
          <td>${e.asset_symbol || e.market || "—"}</td>
          <td>${(e.direction || "").toUpperCase() || "—"}</td>
          <td class="mono ${(e.pnl_pct ?? 0) >= 0 ? "text-up" : "text-down"}">${e.pnl_pct !== undefined && e.pnl_pct !== null ? e.pnl_pct + "%" : "—"}</td>
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
