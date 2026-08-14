import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";
import { emptyStateHtml } from "../components/emptyState.js";

export function renderAlerts(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="alerts-list" class="grid" style="grid-template-columns:1fr;"></div>
  `;

  renderAsync(
    main.querySelector("#alerts-list"),
    () => api.get("/notifications"),
    (data) => {
      // Field confirmed against the live GET /api/v1/notifications
      // response: `is_read` (not "read").
      const items = data.notifications || [];
      if (!items.length) return `<div class="card">${emptyStateHtml("No alerts yet.", "\u{1F514}")}</div>`;
      return items.map((n) => `
        <div class="card card-hover" style="display:flex; justify-content:space-between; align-items:center;">
          <div>
            <div style="font-weight:600;">${n.title || "—"}</div>
            <div class="text-2" style="font-size:12px; margin-top:2px;">${n.message || ""}</div>
            <div class="text-3" style="font-size:11px; margin-top:4px;">${n.created_at || ""}</div>
          </div>
          ${n.is_read ? "" : '<span class="badge badge-warn">NEW</span>'}
        </div>
      `).join("");
    },
  );
}
