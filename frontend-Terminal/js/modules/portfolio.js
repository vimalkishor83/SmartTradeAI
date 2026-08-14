import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";

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
      if (!items.length) return `<div class="text-3">No portfolio holdings yet.</div>`;
      const rows = items.map((i) => `
        <tr>
          <td>${i.symbol || i.asset_symbol || "—"}</td>
          <td class="mono">${i.quantity ?? "—"}</td>
          <td class="mono">${i.avg_price ?? i.entry_price ?? "—"}</td>
          <td class="mono">${i.current_value ?? "—"}</td>
        </tr>
      `).join("");
      return `
        <table class="data-table">
          <thead><tr><th>Asset</th><th>Qty</th><th>Avg price</th><th>Value</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    },
  );
}
