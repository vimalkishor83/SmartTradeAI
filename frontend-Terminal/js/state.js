const listeners = new Set();

const state = {
  user: null,
  token: localStorage.getItem("stt_token") || null,
  activeModule: null,
};

export function getState() {
  return state;
}

export function setState(patch) {
  Object.assign(state, patch);
  if ("token" in patch) {
    if (patch.token) localStorage.setItem("stt_token", patch.token);
    else localStorage.removeItem("stt_token");
  }
  listeners.forEach((fn) => fn(state));
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
