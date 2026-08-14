import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";
import { emptyStateHtml } from "../components/emptyState.js";

export function renderWatchlist(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="watchlist-table" class="card"></div>
  `;

  renderAsync(
    main.querySelector("#watchlist-table"),
    () => api.get("/watchlist"),
    (data) => {
      // Real GET /api/v1/watchlist response nests items under named lists:
      // { watchlists: [{ name, items: [{ symbol, name, market }] }] } — not
      // a flat items[]/watchlists[] array of assets as originally guessed.
      const lists = data.watchlists || [];
      const rows = lists.flatMap((list) =>
        (list.items || []).map((i) => `
          <tr>
            <td>${i.symbol || "—"}</td>
            <td class="text-2">${i.name || ""}</td>
            <td class="text-3">${list.name || "—"}</td>
          </tr>
        `)
      );
      if (!rows.length) return emptyStateHtml("No watchlist items yet.", "☆");
      return `
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>Symbol</th><th>Name</th><th>List</th></tr></thead>
            <tbody>${rows.join("")}</tbody>
          </table>
        </div>
      `;
    },
  );
}
