import { api } from "../api.js";
import { getState } from "../state.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";

export function renderAdmin(main, mod) {
  const { user } = getState();
  const isAdmin = user && (user.role === "admin" || user.is_admin);

  if (!isAdmin) {
    main.innerHTML = `
      ${pageHeaderHtml(mod.label)}
      <div class="card" style="text-align:center; padding:48px;">
        <div style="font-size:28px; margin-bottom:8px;">\u{1F512}</div>
        <h2 style="margin:0 0 6px;">Restricted to administrators</h2>
        <p class="text-2">Your account doesn't have admin access. Contact the desk if you believe this is a mistake.</p>
      </div>
    `;
    return;
  }

  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="admin-pending" class="card"></div>
  `;

  renderAsync(
    main.querySelector("#admin-pending"),
    () => api.get("/admin/users?status=pending"),
    (data) => {
      const users = data.users || data.items || data || [];
      if (!users.length) return `<div class="text-3">No pending approvals.</div>`;
      return `
        <table class="data-table">
          <thead><tr><th>Name</th><th>Email</th><th>Requested</th></tr></thead>
          <tbody>
            ${users.map((u) => `
              <tr>
                <td>${u.name || "—"}</td>
                <td>${u.email || "—"}</td>
                <td class="text-3">${u.created_at || ""}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `;
    },
  );
}
