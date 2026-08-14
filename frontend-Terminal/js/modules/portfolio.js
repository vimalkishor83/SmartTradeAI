import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";
import { emptyStateHtml } from "../components/emptyState.js";

export function renderPortfolio(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="portfolio-table" class="card"></div>
  `;

  renderAsync(
    main.querySelector("#portfolio-table"),
    () => api.get("/portfolio"),
    (data) => {
      const items = data.items || data.holdings || data || [];
      if (!items.length) return emptyStateHtml("No portfolio holdings yet.", "\u{1F4BC}");
      const rows = items.map((i) => `
        <tr>
          <td>${i.symbol || i.asset_symbol || "—"}</td>
          <td class="mono">${i.quantity ?? "—"}</td>
          <td class="mono">${i.avg_price ?? i.entry_price ?? "—"}</td>
          <td class="mono">${i.current_value ?? "—"}</td>
        </tr>
      `).join("");
      return `
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>Asset</th><th>Qty</th><th>Avg price</th><th>Value</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      `;
    },
  );
}
