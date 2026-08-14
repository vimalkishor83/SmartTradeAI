import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";

export function renderCharts(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="charts-list" class="card"></div>
  `;

  renderAsync(
    main.querySelector("#charts-list"),
    () => api.get("/market-data/live-prices"),
    (data) => {
      const rows = data.prices || data.items || data || [];
      if (!rows.length) return `<div class="text-3">No live price data yet.</div>`;
      return `
        <table class="data-table">
          <thead><tr><th>Asset</th><th>Price</th><th>Change</th></tr></thead>
          <tbody>
            ${rows.map((r) => `
              <tr>
                <td>${r.symbol || r.asset_symbol || "—"}</td>
                <td class="mono">${r.price ?? r.last_price ?? "—"}</td>
                <td class="mono ${(r.change_pct ?? r.change ?? 0) >= 0 ? "text-up" : "text-down"}">${r.change_pct ?? r.change ?? "—"}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `;
    },
  );
}
