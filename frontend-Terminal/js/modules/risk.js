import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { statCardHtml } from "../components/statCard.js";
import { renderAsync } from "../components/asyncSection.js";

export function renderRisk(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="risk-stats" class="stat-row"></div>
  `;

  renderAsync(
    main.querySelector("#risk-stats"),
    () => api.get("/risk/portfolio"),
    (data) => [
      statCardHtml({ label: "Portfolio risk", value: data.total_risk_pct !== undefined ? `${data.total_risk_pct}%` : "—" }),
      statCardHtml({ label: "Open exposure", value: data.total_exposure ?? "—" }),
      statCardHtml({ label: "Largest position risk", value: data.max_position_risk_pct !== undefined ? `${data.max_position_risk_pct}%` : "—" }),
    ].join(""),
  );
}
