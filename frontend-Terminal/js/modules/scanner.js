import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";
import { emptyStateHtml } from "../components/emptyState.js";

export function renderScanner(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="scanner-table" class="card"></div>
  `;

  // Scanner has no GET list endpoint — only POST /scanner/run with a
  // filters body (confirmed via app/api/v1/scanner.py). Run the default
  // "strong_buy" filter across the daily timeframe as a sensible landing view.
  renderAsync(
    main.querySelector("#scanner-table"),
    () => api.post("/scanner/run", { filters: ["strong_buy", "strong_sell", "breakout", "breakdown"], timeframe: "1d" }),
    (data) => {
      const rows = data.results || [];
      if (!rows.length) return emptyStateHtml("No assets currently match the scan filters.", "⇄");
      return `
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>Asset</th><th>Price</th><th>Change</th><th>RSI</th><th>Matched</th></tr></thead>
            <tbody>
              ${rows.map((r) => `
                <tr>
                  <td>${r.symbol || "—"}</td>
                  <td class="mono">${r.price ?? "—"}</td>
                  <td class="mono ${(r.change_pct ?? 0) >= 0 ? "text-up" : "text-down"}">${r.change_pct !== undefined ? r.change_pct + "%" : "—"}</td>
                  <td class="mono">${r.rsi !== undefined && r.rsi !== null ? Math.round(r.rsi) : "—"}</td>
                  <td class="text-2" style="font-size:12px;">${(r.matched_filters || []).join(", ")}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      `;
    },
  );
}
