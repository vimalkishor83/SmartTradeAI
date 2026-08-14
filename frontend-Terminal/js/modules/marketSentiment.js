import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { statCardHtml } from "../components/statCard.js";
import { renderAsync } from "../components/asyncSection.js";
import { emptyStateHtml } from "../components/emptyState.js";

export function renderMarketSentiment(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="sentiment-content"></div>
  `;

  renderAsync(
    main.querySelector("#sentiment-content"),
    () => api.get("/sentiment/fear-greed"),
    (payload) => {
      const d = payload.data || {};
      if (!d.current) return `<div class="card">${emptyStateHtml(d.note || "Sentiment data unavailable.", "\u{1F9ED}")}</div>`;
      const tone = d.current.value <= 25 ? "down" : d.current.value >= 75 ? "up" : "warn";
      const rows = (d.history || []).slice(0, 10).map((h) => `
        <tr>
          <td class="mono">${new Date(h.timestamp * 1000).toLocaleDateString()}</td>
          <td class="mono">${h.value}</td>
          <td>${h.classification}</td>
        </tr>
      `).join("");
      return `
        <div class="stat-row">
          ${statCardHtml({ label: "Crypto Fear & Greed", value: d.current.value, sub: d.current.classification, tone })}
        </div>
        <div class="card">
          <div class="page-desc" style="margin-bottom:8px;">Last 10 days</div>
          <div class="table-wrap">
            <table class="data-table">
              <thead><tr><th>Date</th><th>Value</th><th>Classification</th></tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>
        <p class="text-3" style="font-size:11px; margin-top:12px;">${d.note || ""} Source: ${d.source || "—"} (${d.scope || ""})</p>
      `;
    },
  );
}
