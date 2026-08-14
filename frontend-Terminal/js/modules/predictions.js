import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";

export function renderPredictions(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="predictions-table" class="card"></div>
  `;

  renderAsync(
    main.querySelector("#predictions-table"),
    () => api.get("/predictions"),
    (data) => {
      const items = data.predictions || data.items || data || [];
      if (!items.length) return `<div class="text-3">No model predictions yet.</div>`;
      return `
        <table class="data-table">
          <thead><tr><th>Asset</th><th>Direction</th><th>Confidence</th><th>Horizon</th></tr></thead>
          <tbody>
            ${items.map((p) => `
              <tr>
                <td>${p.symbol || p.asset_symbol || "—"}</td>
                <td>${(p.direction || "").toUpperCase() || "—"}</td>
                <td class="mono">${p.confidence !== undefined ? Math.round(p.confidence <= 1 ? p.confidence * 100 : p.confidence) + "%" : "—"}</td>
                <td>${p.horizon || "—"}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `;
    },
  );
}
