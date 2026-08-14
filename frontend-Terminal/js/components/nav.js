import { MODULE_GROUPS } from "../moduleRegistry.js";
import { navigate, currentRouteId } from "../router.js";
import { subscribe } from "../state.js";

export function mountNav(root) {
  function render() {
    const activeId = currentRouteId();
    root.innerHTML = `
      <nav class="sidenav">
        ${MODULE_GROUPS.map((group) => `
          <div class="sidenav-section">${group.label}</div>
          ${group.items.map((item) => `
            <div class="sidenav-item ${item.id === activeId ? "active" : ""}" data-id="${item.id}">
              <span class="nav-icon">${item.icon}</span>
              <span>${item.label}</span>
              ${item.real ? "" : '<span class="nav-soon">SOON</span>'}
            </div>
          `).join("")}
        `).join("")}
      </nav>
    `;
    root.querySelectorAll(".sidenav-item").forEach((el) => {
      el.addEventListener("click", () => navigate(el.dataset.id));
    });
  }

  render();
  window.addEventListener("hashchange", render);
  subscribe(render);
}
