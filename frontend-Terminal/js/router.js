const routes = new Map();
let notFoundHandler = () => {};
let currentCleanup = null;

export function registerRoute(id, handler) {
  routes.set(id, handler);
}

export function setNotFound(handler) {
  notFoundHandler = handler;
}

export function currentRouteId() {
  const hash = window.location.hash.replace(/^#\/?/, "");
  return hash || "home";
}

export async function resolveRoute() {
  if (typeof currentCleanup === "function") {
    try { currentCleanup(); } catch { /* ignore */ }
    currentCleanup = null;
  }
  const id = currentRouteId();
  const handler = routes.get(id) || notFoundHandler;
  const cleanup = await handler(id);
  if (typeof cleanup === "function") currentCleanup = cleanup;
}

export function navigate(id) {
  window.location.hash = `/${id}`;
}

export function startRouter() {
  window.addEventListener("hashchange", resolveRoute);
  resolveRoute();
}
