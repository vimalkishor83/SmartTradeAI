import { ApiError } from "../api.js";

// Renders a loading state into `el`, calls `fetcher()`, then renders
// the result via `renderFn(data)` or an error state on failure.
export async function renderAsync(el, fetcher, renderFn) {
  el.innerHTML = `<div class="card text-3">Loading…</div>`;
  try {
    const data = await fetcher();
    el.innerHTML = renderFn(data);
  } catch (err) {
    const msg = err instanceof ApiError ? err.message : "Couldn't load this module's data.";
    el.innerHTML = `<div class="card text-down">${msg}</div>`;
  }
}
