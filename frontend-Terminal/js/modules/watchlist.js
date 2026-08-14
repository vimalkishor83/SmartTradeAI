import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";

export function renderWatchlist(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="watchlist-table" class="card"></div>
  `;

  renderAsync(
    main.querySelector("#watchlist-table"),
    () => api.get("/watchlist"),
    (data) => {
      const items = data.items || data.watchlists || data || [];
      if (!items.length) return `<div class="text-3">No watchlist items yet.</div>`;
      const rows = items.map((i) => `
        <tr>
          <td>${i.symbol || i.asset_symbol || i.name || "—"}</td>
          <td class="text-2">${i.note || i.context || ""}</td>
        </tr>
      `).join("");
      return `
        <table class="data-table">
          <thead><tr><th>Asset</th><th>Note</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    },
  );
}
