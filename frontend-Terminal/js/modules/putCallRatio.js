import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";
import { emptyStateHtml } from "../components/emptyState.js";

export function renderPutCallRatio(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="pcr-content" class="card"></div>
  `;

  renderAsync(
    main.querySelector("#pcr-content"),
    () => api.get("/put-call-ratio"),
    (payload) => {
      const d = payload.data || {};
      const instruments = d.instruments || [];
      if (!instruments.length) return emptyStateHtml(d.note || "No put/call data available.", "☯");
      const rows = instruments.map((i) => {
        if (!i.available) {
          return `<tr><td>${i.currency}</td><td colspan="3" class="text-3">Unavailable</td></tr>`;
        }
        return `
          <tr>
            <td>${i.currency}</td>
            <td class="mono">${i.put_call_oi_ratio ?? "—"}</td>
            <td class="mono">${i.put_call_volume_ratio ?? "—"}</td>
            <td class="text-2" style="font-size:12px;">OI: ${i.call_open_interest} calls / ${i.put_open_interest} puts</td>
          </tr>
        `;
      }).join("");
      return `
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>Instrument</th><th>P/C (open interest)</th><th>P/C (24h volume)</th><th>Detail</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <p class="text-3" style="font-size:11px; margin-top:12px;">${d.note || ""} Source: ${d.source || "—"} (${d.scope || ""})</p>
      `;
    },
  );
}
