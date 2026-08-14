import { api } from "../api.js";
import { getState } from "../state.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";
import { emptyStateHtml } from "../components/emptyState.js";

export function renderAdmin(main, mod) {
  const { user } = getState();
  const isAdmin = user && (user.role === "admin" || user.is_admin);

  if (!isAdmin) {
    main.innerHTML = `
      ${pageHeaderHtml(mod.label)}
      <div class="card soon-card">
        <div class="icon-badge">\u{1F512}</div>
        <h2>Restricted to administrators</h2>
        <p>Your account doesn't have admin access. Contact the desk if you believe this is a mistake.</p>
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
      // Field confirmed against the live GET /api/v1/admin/users response:
      // `full_name` (not "name").
      const users = data.users || [];
      if (!users.length) return emptyStateHtml("No pending approvals.", "\u{2699}");
      return `
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>Name</th><th>Email</th><th>Requested</th></tr></thead>
            <tbody>
              ${users.map((u) => `
                <tr>
                  <td>${u.full_name || u.username || "—"}</td>
                  <td>${u.email || "—"}</td>
                  <td class="text-3">${u.created_at || ""}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      `;
    },
  );
}
