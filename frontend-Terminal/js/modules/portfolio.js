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
      // Field names confirmed against the live GET /api/v1/portfolio
      // response: `asset`, `buy_price`, `current_value`, `pnl_pct` — not
      // "symbol"/"avg_price" as originally guessed.
      const items = data.holdings || [];
      if (!items.length) return emptyStateHtml("No portfolio holdings yet.", "\u{1F4BC}");
      const rows = items.map((i) => `
        <tr>
          <td>${i.asset || "—"}</td>
          <td class="mono">${i.quantity ?? "—"}</td>
          <td class="mono">${i.buy_price ?? "—"}</td>
          <td class="mono">${i.current_value !== undefined ? i.current_value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"}</td>
          <td class="mono ${(i.pnl_pct ?? 0) >= 0 ? "text-up" : "text-down"}">${i.pnl_pct !== undefined ? i.pnl_pct + "%" : "—"}</td>
        </tr>
      `).join("");
      return `
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>Asset</th><th>Qty</th><th>Buy price</th><th>Value</th><th>P&L</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      `;
    },
  );
}
