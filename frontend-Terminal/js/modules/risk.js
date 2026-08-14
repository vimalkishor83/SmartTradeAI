import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { statCardHtml } from "../components/statCard.js";
import { renderAsync } from "../components/asyncSection.js";
import { emptyStateHtml } from "../components/emptyState.js";

export function renderRisk(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="risk-stats" class="stat-row"></div>
    <div id="risk-detail"></div>
  `;

  renderAsync(
    main.querySelector("#risk-stats"),
    () => api.get("/risk/portfolio"),
    (data) => {
      // Field names confirmed against the live GET /api/v1/risk/portfolio
      // response: {concentration: {total_value, by_symbol, by_market,
      // warnings}, correlation: {high_correlation_pairs}, holdings: N} —
      // not the flat {total_risk_pct, total_exposure} originally guessed.
      const holdingsCount = data.holdings ?? 0;
      return [
        statCardHtml({ label: "Holdings", value: holdingsCount }),
        statCardHtml({ label: "Total value", value: data.concentration?.total_value !== undefined ? data.concentration.total_value.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "—" }),
        statCardHtml({ label: "Largest position", value: data.concentration?.by_symbol?.[0] ? `${data.concentration.by_symbol[0].symbol} (${data.concentration.by_symbol[0].pct}%)` : "—", tone: (data.concentration?.by_symbol?.[0]?.pct || 0) > 40 ? "warn" : undefined }),
        statCardHtml({ label: "High-correlation pairs", value: data.correlation?.high_correlation_pairs?.length ?? 0 }),
      ].join("");
    },
  );

  renderAsync(
    main.querySelector("#risk-detail"),
    () => api.get("/risk/portfolio"),
    (data) => {
      const warnings = data.concentration?.warnings || [];
      const bySymbol = data.concentration?.by_symbol || [];
      if (!bySymbol.length) return emptyStateHtml("No portfolio positions to assess risk for yet.", "\u{1F6E1}");
      const rows = bySymbol.map((s) => `
        <tr><td>${s.symbol}</td><td class="mono">${s.value.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td><td class="mono">${s.pct}%</td></tr>
      `).join("");
      const warningCards = warnings.map((w) => `<div class="card" style="margin-bottom:8px;"><span class="badge badge-warn">RISK</span> <span class="text-2" style="font-size:12px;">${w}</span></div>`).join("");
      return `
        ${warningCards}
        <div class="card">
          <div class="page-desc" style="margin-bottom:8px;">Concentration by symbol</div>
          <div class="table-wrap">
            <table class="data-table">
              <thead><tr><th>Symbol</th><th>Value</th><th>% of portfolio</th></tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>
      `;
    },
  );
}
