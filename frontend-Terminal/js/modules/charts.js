import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";
import { emptyStateHtml } from "../components/emptyState.js";

export function renderCharts(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="charts-list" class="card"></div>
  `;

  renderAsync(
    main.querySelector("#charts-list"),
    () => api.get("/market-data/live-prices"),
    (data) => {
      // `prices` is a dict keyed by symbol (confirmed against the live
      // GET /api/v1/market-data/live-prices response), not an array —
      // treating it as one meant `.length` was always undefined and this
      // module showed "no data" regardless of how much live data existed.
      const rows = Object.values(data.prices || {});
      if (!rows.length) return emptyStateHtml("No live price data yet.", "\u{1F4CA}");
      return `
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>Asset</th><th>Price</th><th>24h high</th><th>24h low</th><th>Change</th></tr></thead>
            <tbody>
              ${rows.map((r) => `
                <tr>
                  <td>${r.symbol || "—"}</td>
                  <td class="mono">${r.price ?? "—"}</td>
                  <td class="mono text-2">${r.high ?? "—"}</td>
                  <td class="mono text-2">${r.low ?? "—"}</td>
                  <td class="mono ${(r.change_pct ?? 0) >= 0 ? "text-up" : "text-down"}">${r.change_pct !== undefined ? r.change_pct + "%" : "—"}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      `;
    },
  );
}
