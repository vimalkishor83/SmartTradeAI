import { getState, setState } from "./state.js";

const API_BASE = "/api/v1";

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  const { token } = getState();
  if (auth && token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    setState({ user: null, token: null });
    throw new ApiError("Session expired — please sign in again.", 401);
  }

  let data = null;
  try {
    data = await res.json();
  } catch {
    /* empty body */
  }

  if (!res.ok) {
    throw new ApiError(data?.message || data?.error || `Request failed (${res.status})`, res.status);
  }

  return data;
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: "POST", body }),
  put: (path, body) => request(path, { method: "PUT", body }),
  patch: (path, body) => request(path, { method: "PATCH", body }),
  del: (path) => request(path, { method: "DELETE" }),
};

export async function login(email, password) {
  const data = await request("/auth/login", { method: "POST", body: { email, password }, auth: false });
  setState({ token: data.access_token || data.token, user: data.user || null });
  if (!data.user) {
    const me = await request("/auth/me");
    setState({ user: me.user || me });
  }
  return data;
}

export function logout() {
  setState({ user: null, token: null });
}

export async function fetchMe() {
  const me = await request("/auth/me");
  const user = me.user || me;
  setState({ user });
  return user;
}

export { ApiError };
