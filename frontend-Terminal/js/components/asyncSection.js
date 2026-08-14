import { ApiError } from "../api.js";

// Renders a loading state into `el`, calls `fetcher()`, then renders
// the result via `renderFn(data)` or an error state on failure.
export async function renderAsync(el, fetcher, renderFn) {
  el.innerHTML = `<div class="card state-block state-loading"><span class="state-icon">\u{23F3}</span><span>Loading…</span></div>`;
  try {
    const data = await fetcher();
    el.innerHTML = renderFn(data);
  } catch (err) {
    const msg = err instanceof ApiError ? err.message : "Couldn't load this module's data.";
    el.innerHTML = `<div class="card state-block state-error"><span class="state-icon">\u{26A0}</span><span>${msg}</span></div>`;
  }
}
