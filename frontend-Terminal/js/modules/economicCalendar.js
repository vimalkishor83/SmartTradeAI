import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";
import { emptyStateHtml } from "../components/emptyState.js";

export function renderEconomicCalendar(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="calendar-table" class="card"></div>
  `;

  renderAsync(
    main.querySelector("#calendar-table"),
    () => api.get("/news/economic-calendar"),
    (data) => {
      const events = data.events || data.items || data || [];
      if (!events.length) return emptyStateHtml("No calendar events yet.", "\u{1F5D3}");
      return `
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>Event</th><th>Country</th><th>Date</th><th>Impact</th></tr></thead>
            <tbody>
              ${events.map((e) => `
                <tr>
                  <td>${e.title || e.event || "—"}</td>
                  <td>${e.country || "—"}</td>
                  <td class="mono">${e.date || e.event_time || "—"}</td>
                  <td>${(e.impact || "").toUpperCase() || "—"}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      `;
    },
  );
}
