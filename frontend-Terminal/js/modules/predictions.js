import { api, ApiError } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { emptyStateHtml } from "../components/emptyState.js";

const PREVIEW_COUNT = 8;

export function renderPredictions(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="predictions-table" class="card"></div>
  `;
  const el = main.querySelector("#predictions-table");
  el.innerHTML = `<div class="state-block state-loading"><span class="state-icon">\u{23F3}</span><span>Loading…</span></div>`;

  // The backend has no "list all predictions" endpoint — only
  // GET /predictions/<asset_id> for one asset at a time (confirmed via
  // app/api/v1/predictions.py), and GET /assets returns ALL active assets
  // with no pagination params (confirmed via app/api/v1/assets.py) — so
  // slice client-side to a small preview set before fetching predictions.
  api.get("/assets")
    .then((assetsData) => {
      const assets = (assetsData.assets || []).slice(0, PREVIEW_COUNT);
      if (!assets.length) {
        el.innerHTML = emptyStateHtml("No tracked assets found.", "\u{1F52E}");
        return;
      }
      return Promise.all(
        assets.map((a) =>
          api.get(`/predictions/${a.id}`)
            .then((p) => ({ asset: a, prediction: p }))
            .catch(() => ({ asset: a, prediction: null }))
        )
      );
    })
    .then((rows) => {
      if (!rows) return;
      const available = rows.filter((r) => r.prediction);
      if (!available.length) {
        el.innerHTML = emptyStateHtml("No model predictions available right now — this is a premium AI feature and may need a subscription plan with predictions enabled.", "\u{1F52E}");
        return;
      }
      el.innerHTML = `
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>Asset</th><th>Direction</th><th>Confidence</th><th>Target</th><th>Timeframe</th></tr></thead>
            <tbody>
              ${available.map(({ asset, prediction: p }) => `
                <tr>
                  <td>${asset.symbol}</td>
                  <td>${p.predicted_direction ? p.predicted_direction.toUpperCase() : "—"}</td>
                  <td class="mono">${p.confidence !== undefined ? Math.round(p.confidence) + "%" : "—"}</td>
                  <td class="mono">${p.predicted_target ?? "—"}</td>
                  <td>${p.timeframe || "—"}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
        <p class="text-3" style="font-size:11px; margin-top:12px;">Preview of ${available.length} tracked instruments. Model: ${available[0]?.prediction?.model_name || "—"}.</p>
      `;
    })
    .catch((err) => {
      el.innerHTML = emptyStateHtml(err instanceof ApiError ? err.message : "Couldn't load predictions.");
    });
}
