import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";

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
      if (!events.length) return `<div class="text-3">No calendar events yet.</div>`;
      return `
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
      `;
    },
  );
}
