import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";

export function renderScanner(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="scanner-table" class="card"></div>
  `;

  renderAsync(
    main.querySelector("#scanner-table"),
    () => api.get("/scanner"),
    (data) => {
      const rows = data.results || data.items || data || [];
      if (!rows.length) return `<div class="text-3">No scanner results yet.</div>`;
      return `
        <table class="data-table">
          <thead><tr><th>Asset</th><th>Bias</th><th>Score</th></tr></thead>
          <tbody>
            ${rows.map((r) => `
              <tr>
                <td>${r.symbol || r.asset_symbol || "—"}</td>
                <td>${(r.bias || r.direction || "").toUpperCase() || "—"}</td>
                <td class="mono">${r.score ?? "—"}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `;
    },
  );
}
