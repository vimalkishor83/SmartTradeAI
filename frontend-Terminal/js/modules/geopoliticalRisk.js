import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { statCardHtml } from "../components/statCard.js";
import { renderAsync } from "../components/asyncSection.js";
import { emptyStateHtml } from "../components/emptyState.js";

export function renderGeopoliticalRisk(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="geo-content"></div>
  `;

  renderAsync(
    main.querySelector("#geo-content"),
    () => api.get("/geopolitical-risk"),
    (payload) => {
      const d = payload.data || {};
      if (d.risk_score === null || d.risk_score === undefined) {
        return `<div class="card">${emptyStateHtml(d.note || "Risk signal unavailable right now.", "⚔")}</div>`;
      }
      const tone = d.risk_label === "elevated" ? "down" : d.risk_label === "moderate" ? "warn" : "up";
      const countryRows = (d.top_countries || []).map((c) => `
        <tr><td>${c.country}</td><td class="mono">${c.count}</td></tr>
      `).join("");
      const headlines = (d.headlines || []).slice(0, 8).map((h) => `
        <div class="card" style="margin-bottom:8px;">
          <a href="${h.url}" target="_blank" rel="noopener" style="font-weight:600;">${h.title || "—"}</a>
          <div class="text-3" style="font-size:11px; margin-top:4px;">${h.domain || ""} ${h.country ? "· " + h.country : ""}</div>
        </div>
      `).join("");
      return `
        <div class="stat-row">
          ${statCardHtml({ label: "Risk score (0-100)", value: d.risk_score, tone })}
          ${statCardHtml({ label: "Risk level", value: (d.risk_label || "—").toUpperCase(), tone })}
          ${statCardHtml({ label: "Articles (24h)", value: d.article_count ?? "—" })}
        </div>
        <div class="grid" style="grid-template-columns: 1fr 1fr; gap:16px; align-items:start;">
          <div>
            <div class="page-desc" style="margin-bottom:8px;">Top source countries (24h)</div>
            <div class="card"><table class="data-table"><thead><tr><th>Country</th><th>Articles</th></tr></thead><tbody>${countryRows || "<tr><td colspan=2 class=text-3>No data</td></tr>"}</tbody></table></div>
          </div>
          <div>
            <div class="page-desc" style="margin-bottom:8px;">Recent headlines</div>
            ${headlines || `<div class="card">${emptyStateHtml("No headlines returned.")}</div>`}
          </div>
        </div>
        <p class="text-3" style="font-size:11px; margin-top:12px;">${d.note || ""} Source: ${d.source || "—"}</p>
      `;
    },
  );
}
