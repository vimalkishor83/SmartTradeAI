import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";
import { emptyStateHtml } from "../components/emptyState.js";

export function renderForexDashboard(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="forex-table" class="card"></div>
  `;

  renderAsync(
    main.querySelector("#forex-table"),
    () => api.get("/forex"),
    (payload) => {
      const d = payload.data || {};
      const pairs = d.pairs || [];
      if (!pairs.length) return emptyStateHtml(d.note || "No forex data available.", "\u{1F4B1}");
      const rows = pairs.map((p) => `
        <tr>
          <td>${p.pair}</td>
          <td class="mono">${p.rate}</td>
          <td class="mono ${p.change_pct_7d < 0 ? "text-up" : p.change_pct_7d > 0 ? "text-down" : ""}">${p.change_pct_7d !== null ? p.change_pct_7d + "%" : "—"}</td>
          <td>${p.strength === "strengthening" ? '<span class="badge badge-up">Strengthening</span>' : p.strength === "weakening" ? '<span class="badge badge-down">Weakening</span>' : "—"}</td>
        </tr>
      `).join("");
      return `
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>Pair</th><th>Rate</th><th>7d change</th><th>USD trend</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <p class="text-3" style="font-size:11px; margin-top:12px;">As of ${d.as_of || "—"} vs ${d.compared_to || "—"} · ${d.note || ""} Source: ${d.source || "—"}</p>
      `;
    },
  );
}
