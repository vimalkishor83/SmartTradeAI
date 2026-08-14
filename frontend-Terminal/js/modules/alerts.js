import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";

export function renderAlerts(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="alerts-list" class="grid" style="grid-template-columns:1fr;"></div>
  `;

  renderAsync(
    main.querySelector("#alerts-list"),
    () => api.get("/notifications"),
    (data) => {
      const items = data.notifications || data.items || data || [];
      if (!items.length) return `<div class="card text-3">No alerts yet.</div>`;
      return items.map((n) => `
        <div class="card" style="display:flex; justify-content:space-between; align-items:center;">
          <div>
            <div style="font-weight:600;">${n.title || n.message || "—"}</div>
            <div class="text-3" style="font-size:11px;">${n.created_at || ""}</div>
          </div>
          ${n.read ? "" : '<span class="badge badge-warn">NEW</span>'}
        </div>
      `).join("");
    },
  );
}
